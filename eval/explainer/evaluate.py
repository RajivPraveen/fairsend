"""Evaluate the plain-language explainer on the reviewed question set.

    python eval/explainer/evaluate.py

Scoring (deterministic, no LLM judge):
  * answerable questions: correct when the assistant answers and every key fact appears in the answer
    (each fact lists acceptable phrasings); cited correctly when at least one cited source is an expected one.
  * questions that must be declined: correct when the assistant declines (advice guard or "I don't know").
  * retrieval hit@5: an expected source is among the five retrieved passages.
Writes eval/results/explainer.json.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import yaml

from fairsend.config import settings
from fairsend.explainer import answer, index

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"


def _norm(text: str) -> str:
    """Lowercase and treat hyphens like spaces ("exchange-rate" matches "exchange rate")."""
    return " ".join(text.lower().replace("-", " ").split())


def facts_present(text: str, key_facts: list[list[str]]) -> list[bool]:
    low = _norm(text)
    return [any(_norm(alt) in low for alt in fact) for fact in key_facts]


def main() -> None:
    items = yaml.safe_load((HERE / "questions.yaml").read_text())
    ix = index.build()
    rows = []
    for it in items:
        start = time.time()
        a = answer.ask(it["question"], index=ix)
        retrieved = [c.source_id for c, _ in a.retrieved]
        if it["answerable"]:
            facts = facts_present(a.text, it["key_facts"]) if a.status == "answered" else [False] * len(it["key_facts"])
            correct = a.status == "answered" and all(facts)
            cited_ok = bool(set(a.cited_source_ids) & set(it["expected_sources"]))
            hit = bool(set(retrieved) & set(it["expected_sources"]))
        else:
            facts, cited_ok, hit = [], None, None
            correct = a.status in ("declined_advice", "not_found")
        rows.append({
            "id": it["id"], "question": it["question"], "answerable": it["answerable"],
            "decline_reason": it.get("decline_reason"), "status": a.status, "correct": correct,
            "facts_found": facts, "cited_correct_source": cited_ok, "retrieval_hit_at_5": hit,
            "cited_sources": a.cited_source_ids, "expected_sources": it.get("expected_sources"),
            "answer": a.text, "seconds": round(time.time() - start, 1),
        })
        r = rows[-1]
        print(f"{it['id']} {'OK ' if correct else 'BAD'} cite={cited_ok} {a.status:16} {r['seconds']}s  {it['question'][:60]}")

    ans = [r for r in rows if r["answerable"]]
    dec = [r for r in rows if not r["answerable"]]
    summary = {
        "model": settings.llm_model, "embedding_model": settings.embed_model, "questions": len(rows),
        "answerable": len(ans), "must_decline": len(dec),
        "answer_accuracy": sum(r["correct"] for r in ans) / len(ans),
        "citation_accuracy": sum(bool(r["cited_correct_source"]) for r in ans) / len(ans),
        "correct_with_right_citation": sum(r["correct"] and r["cited_correct_source"] for r in ans) / len(ans),
        "retrieval_hit_at_5": sum(bool(r["retrieval_hit_at_5"]) for r in ans) / len(ans),
        "decline_accuracy": sum(r["correct"] for r in dec) / len(dec) if dec else None,
        "decline_accuracy_out_of_scope": _share(dec, "out_of_scope"),
        "decline_accuracy_personal_advice": _share(dec, "personal_advice"),
        "false_declines": sum(r["status"] != "answered" for r in ans),
        "mean_seconds": sum(r["seconds"] for r in rows) / len(rows),
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "explainer.json").write_text(json.dumps({"summary": summary, "questions": rows}, indent=2))
    print(json.dumps(summary, indent=2))


def _share(rows: list[dict], reason: str) -> float | None:
    sub = [r for r in rows if r["decline_reason"] == reason]
    return sum(r["correct"] for r in sub) / len(sub) if sub else None


if __name__ == "__main__":
    main()
