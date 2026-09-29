"""Answer questions about transfer pricing from the vetted source library only, with citations.

Guardrails, in order:
  1. Requests for personal financial advice or rate predictions are declined up front.
  2. If no passage is similar enough to the question, the assistant says it doesn't know.
  3. The local LLM is told to answer only from the numbered passages and to cite them; it can reply
     NOT_IN_SOURCES. Answers without a valid citation are retried once, then withheld.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from fairsend import llm
from fairsend.explainer import index as idx

MIN_SCORE = 0.30     # cosine similarity below which a passage is considered unrelated
TOP_K = 5            # passages given to the model (3 was faster to read but dropped accuracy from 89% to 73%)
NUM_PREDICT = 500    # cap on answer length (tokens)

ADVICE_PATTERNS = [
    r"\bshould i\b.*\b(wait|hold|buy|sell|invest|convert now|send now|time)\b",
    r"\b(will|is) the (rate|rupee|dollar|peso|euro|pound|naira|currency|exchange rate)\b.*\b(go|rise|fall|drop|climb|increase|decrease|up|down)\b",
    r"\b(predict|forecast|prediction)\b",
    r"\b(best|good|right|bad|ideal) (time|moment|day|week|month) to\b",   # market timing
    r"\bis (now|today|this week|this month) (a )?(good|bad|the right|the best)\b",
    r"\b(wait|hold off|hold on) (until|till|for)\b.*\b(rate|rupee|dollar|peso|euro|pound|naira|currency)\b",
    r"\bshould i (convert|exchange|change|move|put|keep)\b",
    r"\b(invest|investment|stock|stocks|crypto|bitcoin|savings account|put my savings|retirement)\b",
    r"\bwhat should i do with my (money|savings)\b",
]
ADVICE_REPLY = (
    "I can't give personal financial advice or predict exchange rates. I can explain how transfer "
    "pricing works, and FairSend's comparison tool can show what each provider costs on your route today."
)
NOT_FOUND_REPLY = (
    "I don't know. My sources (U.S. CFPB rules and guidance, World Bank remittance price methodology, "
    "the UN remittance target, and FairSend's methodology) don't cover that question."
)

SYSTEM = (
    "You explain international money transfer pricing and consumer rights to non-experts. Use ONLY the "
    "numbered sources provided. Cite every claim with the source number in square brackets, like [1] or [2][3]. "
    "Write 2-5 short, plain sentences. When the sources list several conditions, cases, or rights, mention each "
    "of them briefly. Do not give personal financial advice. Reply with exactly NOT_IN_SOURCES only if none of "
    "the sources is relevant to the question; if they are relevant, answer from them."
)


@dataclass
class Answer:
    question: str
    text: str
    status: str                       # answered | declined_advice | not_found | llm_unavailable
    citations: list[idx.Chunk] = field(default_factory=list)
    retrieved: list[tuple[idx.Chunk, float]] = field(default_factory=list)

    @property
    def cited_source_ids(self) -> list[str]:
        return list(dict.fromkeys(c.source_id for c in self.citations))


def is_advice_request(question: str) -> bool:
    q = question.lower()
    return any(re.search(p, q) for p in ADVICE_PATTERNS)


def _prompt(question: str, passages: list[tuple[idx.Chunk, float]], strict: bool = False) -> str:
    blocks = [f"[{i}] {c.title} ({c.publisher}), section \"{c.section}\":\n{c.text}"
              for i, (c, _) in enumerate(passages, start=1)]
    reminder = ("\nRemember: every sentence must end with a citation like [1]. "
                "If the sources don't answer it, reply NOT_IN_SOURCES.") if strict else ""
    return "Sources:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}{reminder}\nAnswer:"


def _citations(text: str, passages: list[tuple[idx.Chunk, float]]) -> tuple[str, list[idx.Chunk]]:
    """Renumber citations 1..n in order of first use and return (text, cited chunks in that order)."""
    order = [int(n) for n in dict.fromkeys(re.findall(r"\[(\d+)\]", text)) if 1 <= int(n) <= len(passages)]
    new_number = {old: new for new, old in enumerate(order, start=1)}

    def swap(m: re.Match) -> str:
        n = int(m.group(1))
        return f"[{new_number[n]}]" if n in new_number else ""

    return re.sub(r"\[(\d+)\]", swap, text), [passages[n - 1][0] for n in order]


def _clean(text: str) -> str:
    text = text.strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def ask(question: str, index: idx.Index | None = None, model: str | None = None,
        on_text: Callable[[str], None] | None = None) -> Answer:
    """Answer from the sources. If `on_text` is given, it is called with the text so far as the model writes."""
    question = question.strip()
    if is_advice_request(question):
        return Answer(question, ADVICE_REPLY, "declined_advice")
    index = index or idx.default_index()
    hits = index.search(question, k=TOP_K)
    passages = [(c, s) for c, s in hits if s >= getattr(index, "min_score", MIN_SCORE)]
    if not passages:
        return Answer(question, NOT_FOUND_REPLY, "not_found", retrieved=hits)
    try:
        for strict in (False, True):
            prompt = _prompt(question, passages, strict)
            if on_text is not None and not strict:
                raw = ""
                for piece in llm.stream(prompt, system=SYSTEM, model=model, num_predict=NUM_PREDICT):
                    raw += piece
                    # hold back the first few characters so a NOT_IN_SOURCES reply is never shown
                    if len(raw) > 16 and not raw.lstrip().startswith("NOT_IN"):
                        on_text(raw)
                raw = _clean(raw)
            else:
                raw = _clean(llm.generate(prompt, system=SYSTEM, model=model, num_predict=NUM_PREDICT))
            if "NOT_IN_SOURCES" in raw:
                return Answer(question, NOT_FOUND_REPLY, "not_found", retrieved=hits)
            text, cites = _citations(raw, passages)
            if cites:
                return Answer(question, text, "answered", cites, hits)
        return Answer(question, NOT_FOUND_REPLY, "not_found", retrieved=hits)
    except llm.LLMUnavailable:
        top = passages[0][0]
        text = f"Here's what the official source says [1]:\n\n{top.text}"
        return Answer(question, text, "llm_unavailable", [top], hits)
