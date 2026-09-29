"""Shared helpers for the Streamlit views: cached data access and formatting."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from fairsend import compare, db, fx

SYMBOLS = {"USD": "$", "GBP": "£", "EUR": "€", "INR": "₹", "PHP": "₱", "NGN": "₦", "JPY": "¥", "KRW": "₩",
           "CAD": "C$", "AUD": "A$", "MXN": "MX$", "BRL": "R$", "VND": "₫", "BDT": "৳", "PKR": "Rs ",
           "CNY": "CN¥", "ZAR": "R ", "KES": "KSh ", "TRY": "₺", "ILS": "₪", "THB": "฿", "UAH": "₴"}

TUITION_CURRENCIES = sorted({
    "USD", "GBP", "EUR", "CAD", "AUD", "NZD", "SGD", "JPY", "CHF", "INR", "CNY", "NGN", "PKR", "BDT", "NPR",
    "VND", "KRW", "MXN", "BRL", "PHP", "KES", "GHS", "TRY", "IDR", "MYR", "THB", "EGP", "SAR", "AED", "LKR",
    "COP", "ZAR", "HKD", "TWD", "SEK", "NOK", "DKK", "PLN", "MAD", "UGX", "ETB", "PEN", "CLP", "ARS",
})


def money(x: float | None, ccy: str, decimals: int | None = None) -> str:
    if x is None or pd.isna(x):
        return "—"
    if decimals is None:
        decimals = 0 if abs(x) >= 1000 else 2
    sym = SYMBOLS.get(ccy)
    s = f"{abs(x):,.{decimals}f}"
    sign = "-" if x < 0 else ""
    return f"{sign}{sym}{s}" if sym else f"{sign}{s} {ccy}"


def md(text: str) -> str:
    """Escape dollar signs for Streamlit markdown, where "$...$" would render as math."""
    return text.replace("$", "\\$")


def pct(x: float | None, decimals: int = 2) -> str:
    return "—" if x is None or pd.isna(x) else f"{x:.{decimals}f}%"


@st.cache_data(ttl=3600, show_spinner=False)
def corridors() -> pd.DataFrame:
    return compare.corridors()


@st.cache_data(ttl=3600, show_spinner=False)
def mid_rate(base: str, quote: str) -> fx.Rate:
    return fx.get_rate(base, quote)


@st.cache_data(ttl=3600, show_spinner=False)
def rate_history(base: str, quote: str, days: int = 90) -> pd.DataFrame:
    end = dt.date.today()
    return fx.get_history(base, quote, end - dt.timedelta(days=days), end)


@st.cache_data(ttl=3600, show_spinner=False)
def run_compare(src: str, dst: str, amount: float, payouts: tuple[str, ...], max_days: float | None,
                mode: str = "budget") -> compare.Comparison:
    return compare.compare(src, dst, amount, payout_methods=list(payouts) or None, max_days=max_days, mode=mode)


@st.cache_data(ttl=3600, show_spinner=False)
def data_freshness() -> dict:
    run = db.query_df("SELECT run_id, finished_at, source_file, rows_in, rows_valid FROM pipeline_runs "
                      "WHERE status='success' ORDER BY finished_at DESC LIMIT 1")
    latest = db.query_df("SELECT MAX(period) AS period, MAX(collected_date) AS collected FROM rpw_prices")
    return {**(run.iloc[0].to_dict() if len(run) else {}), **latest.iloc[0].to_dict()}


@st.cache_data(show_spinner=False)
def _iso2() -> dict[str, str]:
    from fairsend.config import REFERENCE_DIR
    ref = pd.read_csv(REFERENCE_DIR / "country_currency.csv", keep_default_na=False)
    return dict(zip(ref["iso3"], ref["iso2"]))


def flag(iso3: str) -> str:
    code = _iso2().get(iso3, "")
    if len(code) != 2 or not code.isalpha():
        return "🌐"
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper())


def _route_selects(key: str, col_from, col_to, default_src: str = "USA", default_dst: str = "IND"):
    cor = corridors()
    qp, prefs = st.query_params, st.session_state
    src_default = qp.get("src") or prefs.get("pref_src", default_src)
    sources = cor.drop_duplicates("source_code").sort_values("source_name")
    src_labels = dict(zip(sources["source_code"], sources["source_name"]))
    src_codes = list(src_labels)
    src = col_from.selectbox("From", src_codes, format_func=lambda c: f"{flag(c)}  {src_labels[c]}",
                             index=src_codes.index(src_default) if src_default in src_codes else 0, key=f"{key}_src")
    dests = cor[cor["source_code"] == src].sort_values("dest_name")
    dst_labels = dict(zip(dests["dest_code"], dests["dest_name"]))
    dst_codes = list(dst_labels)
    dst_default = qp.get("dst") or prefs.get("pref_dst", default_dst)
    dst = col_to.selectbox("To", dst_codes, format_func=lambda c: f"{flag(c)}  {dst_labels[c]}",
                           index=dst_codes.index(dst_default) if dst_default in dst_codes else 0, key=f"{key}_dst")
    prefs["pref_src"], prefs["pref_dst"] = src, dst
    return src, dst, cor[(cor["source_code"] == src) & (cor["dest_code"] == dst)].iloc[0]


def route_picker(key: str) -> tuple[str, str, pd.Series]:
    """From / To country pickers over surveyed routes. Remembered across pages; ?src=&dst= pre-fills them."""
    c1, c2 = st.columns(2)
    return _route_selects(key, c1, c2)


def transfer_inputs(key: str, default_amount: float = 500.0) -> tuple[float, str, str, pd.Series]:
    """One row: amount, from, to. Returns (amount, source code, destination code, route row)."""
    c_amt, c_from, c_to = st.columns([1, 1.25, 1.25])
    src, dst, route = _route_selects(key, c_from, c_to)
    qp_amount = st.query_params.get("amount")
    start = float(qp_amount) if qp_amount else float(st.session_state.get("pref_amount", default_amount))
    amt_key = f"{key}_amount"
    if amt_key not in st.session_state:
        st.session_state[amt_key] = max(start, 10.0)
    amount = c_amt.number_input(f"Amount ({route['send_currency']})", min_value=10.0, max_value=1_000_000.0,
                                step=50.0, key=amt_key)
    st.session_state["pref_amount"] = amount
    return amount, src, dst, route


def to_usd(amount: float, currency: str) -> float | None:
    if currency == "USD":
        return amount
    try:
        return amount * mid_rate(currency, "USD").rate
    except fx.RateUnavailable:
        return None


def estimates_note(period: str, collected: str | None, rate: fx.Rate) -> None:
    import theme
    theme.note(
        f"Estimate. Provider prices come from the World Bank's survey of real providers ({period.replace('_', ' ')}, "
        f"collected {collected or 'n/a'}), applied to today's real exchange rate ({rate.source}, {rate.rate_date}). "
        "Always check the provider's own quote before you pay."
    )


@st.cache_data(ttl=6 * 3600, show_spinner="Crunching 250,000 World Bank prices...")
def global_numbers() -> dict:
    from fairsend.analysis import global_costs as g
    df = g.load()
    return {**g.headline_numbers(df), **g.markup_share(df)}
