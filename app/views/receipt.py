import datetime as dt
import html

import streamlit as st

import common
import theme
from fairsend import fx, llm
from fairsend.receipts import checker, ocr
from fairsend.receipts.extract import CODES, Extraction

theme.header("Check a past receipt", "Upload a receipt, or type in the numbers from it. We'll tell you how much the "
                                      "exchange rate secretly cost you, on top of the fee.")

upload = st.file_uploader("Receipt (screenshot or PDF)", type=["png", "jpg", "jpeg", "pdf", "webp"])
theme.note("Your receipt is read on this computer and never saved or uploaded.")

if upload is not None:
    key = f"{upload.name}-{upload.size}"
    if st.session_state.get("receipt_key") != key:
        with st.spinner("Reading your receipt..."):
            try:
                _, fields = checker.check_document(upload.getvalue(), use_llm=llm.available())
            except ocr.OCRUnavailable as exc:
                st.error(f"The receipt reader isn't installed: {exc}")
                st.stop()
        st.session_state.update(receipt_key=key, receipt_fields=fields)
fields: Extraction = st.session_state.get("receipt_fields") or Extraction(method="manual")
if upload is not None:
    st.success("Receipt read. Check the numbers below and fix anything that looks wrong.")

codes = sorted(CODES)
with st.form("receipt_form", border=True):
    c1, c2, c3 = st.columns(3)
    amount_sent = c1.number_input("You sent", min_value=0.0, value=float(fields.amount_sent or 0.0), step=10.0,
                                  help="The amount converted, not counting the fee")
    send_ccy = c2.selectbox("Currency", codes, index=codes.index(fields.send_currency)
                            if fields.send_currency in codes else codes.index("USD"))
    fee = c3.number_input("Fee", min_value=0.0, value=float(fields.fee or 0.0), step=0.5)
    c4, c5, c6 = st.columns(3)
    received = c4.number_input("They received", min_value=0.0, value=float(fields.amount_received or 0.0), step=10.0)
    recv_ccy = c5.selectbox("Currency ", codes, index=codes.index(fields.receive_currency)
                            if fields.receive_currency in codes else codes.index("INR"))
    try:
        default_date = dt.date.fromisoformat(fields.transfer_date) if fields.transfer_date else dt.date.today()
    except ValueError:
        default_date = dt.date.today()
    date = c6.date_input("Date", value=default_date, max_value=dt.date.today())
    rate = st.number_input("Exchange rate on the receipt (optional)", min_value=0.0,
                           value=float(fields.exchange_rate or 0.0), format="%.4f",
                           help="Leave at 0 and we'll work it out from the two amounts.")
    submitted = st.form_submit_button("Check this transfer", type="primary")

if submitted:
    confirmed = Extraction(amount_sent=amount_sent or None, send_currency=send_ccy, fee=fee,
                           exchange_rate=rate or None, amount_received=received or None, receive_currency=recv_ccy,
                           transfer_date=date.isoformat(), method="confirmed")
    try:
        r = checker.check_fields(confirmed)
    except checker.IncompleteReceipt:
        st.error("Please fill in how much you sent and how much they received (or the exchange rate).")
        st.stop()
    except fx.RateUnavailable:
        st.error(f"We don't have the real exchange rate for {send_ccy} to {recv_ccy} on that date.")
        st.stop()
    hidden = max(r.markup_cost, 0)
    theme.answer(
        "Hidden cost", common.money(hidden, send_ccy),
        detail=(f"You got <b>{r.provider_rate:,.2f} {recv_ccy}</b> per {send_ccy}. The real exchange rate that day "
                f"was <b>{r.mid_rate.rate:,.2f}</b>. On {common.money(amount_sent, send_ccy)}, that gap cost you "
                f"{common.money(hidden, send_ccy)}, on top of the {common.money(r.fee, send_ccy)} fee. "
                f"In total the transfer cost <b>{common.money(r.total_cost, send_ccy)}</b> "
                f"({r.total_cost_pct:.1f}% of what you sent)."),
        good=hidden < 0.5,
    )
    theme.cost_bar(r.fee, hidden, f"Fee {common.money(r.fee, send_ccy)}",
                   f"Hidden in the exchange rate {common.money(hidden, send_ccy)}")
    if abs(r.markup_pct) > 10:
        st.warning("That's unusually high. Please double-check the amounts, currencies and date.")
    theme.note(f"Real rate: {html.escape(r.mid_rate.source)}, {r.mid_rate.rate_date}. Rates move during the day, so "
               "small differences are normal.")
    st.page_link("views/compare.py", label="Compare providers for next time", icon=":material/arrow_forward:")
