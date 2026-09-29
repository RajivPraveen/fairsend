import re

import streamlit as st

import common
import theme
from fairsend import llm
from fairsend.explainer import answer as ans
from fairsend.explainer import index as idx

theme.header("Ask", "Confused by a term, a fee, or your rights? Ask in plain words. Answers come only from official "
                    "sources, and each one shows where it came from. We don't give personal financial advice.")


@st.cache_resource(show_spinner="Getting ready...")
def load_index() -> idx.Index:
    return idx.default_index()   # shared with the background warm-up started in FairSend.py


@st.cache_resource
def answer_cache() -> dict:
    """Answers already written in this app session, shared by all visitors. Same question = instant answer."""
    return {}


def render(a: ans.Answer) -> str:
    body = common.md(a.text)
    if a.citations:
        body += "\n\n" + "\n".join(f"{i}. [{c.title}]({c.url}), “{c.section}”"
                                   for i, c in enumerate(a.citations, start=1))
    return body


index = load_index()
if not llm.available():
    st.info("The answer writer (a local AI model) isn't running, so you'll see the most relevant source text instead.")

EXAMPLES = ["Why isn't a zero-fee transfer free?", "What is the real exchange rate?",
            "How long do I have to cancel a transfer?", "The money never arrived. What can I do?"]

if "chat" not in st.session_state:
    st.session_state["chat"] = []

picked = None
if not st.session_state["chat"]:
    st.caption("Try one of these:")
    for q in EXAMPLES:
        if st.button(q, key=f"ex_{q}", type="tertiary", icon=":material/chat_bubble:"):
            picked = q

for turn in st.session_state["chat"]:
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])

question = st.chat_input("Type your question") or picked
if question:
    st.session_state["chat"].append({"role": "user", "content": common.md(question)})
    with st.chat_message("user"):
        st.markdown(common.md(question))
    with st.chat_message("assistant"):
        cache = answer_cache()
        key = " ".join(question.lower().split())
        if key in cache:
            body = cache[key]
        else:
            box = st.empty()
            box.markdown("_Looking it up..._")

            def show(text_so_far: str) -> None:
                # citations are renumbered once the answer is complete; hide them while it's being written
                box.markdown(common.md(re.sub(r"\s*\[\d+\]", "", text_so_far)) + " ▍")

            a = ans.ask(question, index=index, on_text=show)
            body = render(a)
            if a.status in ("answered", "declined_advice", "not_found"):
                cache[key] = body
            box.empty()
        st.markdown(body)
    st.session_state["chat"].append({"role": "assistant", "content": body})
