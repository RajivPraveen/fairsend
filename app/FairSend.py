"""FairSend web app. Run with:  streamlit run app/FairSend.py"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import theme  # noqa: E402

st.set_page_config(page_title="FairSend", page_icon="💵", layout="centered", initial_sidebar_state="collapsed")
theme.inject_css()
theme.register_plotly_template()


@st.cache_resource(show_spinner="Loading World Bank prices (first start only)...")
def ensure_data() -> str:
    """Use the local database if there is one; otherwise download the published demo copy."""
    from fairsend import demo
    return demo.ensure_database()


if ensure_data() == "missing":
    st.error("No price data yet. Run `make data` to build the database from the World Bank file.")
    st.stop()


@st.cache_resource
def warm_up_ask() -> bool:
    """Once per server: load the search index and the local AI model in the background, so the first question
    on the Ask page doesn't wait for them."""
    def run() -> None:
        try:
            from fairsend import llm
            from fairsend.explainer import answer, index
            index.default_index()
            llm.warm_up(system=answer.SYSTEM)
        except Exception:
            pass  # Ask still works; it just loads on first use
    threading.Thread(target=run, daemon=True, name="fairsend-warmup").start()
    return True


warm_up_ask()

MARK = Path(__file__).resolve().parent / "static" / "fairsend_mark.svg"
if not MARK.exists():
    MARK.write_text(theme.LOGO_MARK)
st.logo(str(MARK), size="large")

VIEWS = Path(__file__).resolve().parent / "views"
nav = st.navigation(
    [
        st.Page(VIEWS / "home.py", title="Home", url_path="home", default=True),
        st.Page(VIEWS / "compare.py", title="Compare providers", url_path="compare"),
        st.Page(VIEWS / "tuition.py", title="Tuition costs", url_path="tuition"),
        st.Page(VIEWS / "receipt.py", title="Check a receipt", url_path="receipt"),
        st.Page(VIEWS / "alerts.py", title="Rate alerts", url_path="alerts"),
        st.Page(VIEWS / "explainer.py", title="Ask", url_path="ask"),
        st.Page(VIEWS / "about.py", title="About", url_path="about"),
    ],
    position="top",
)
nav.run()
