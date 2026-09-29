import datetime as dt
import html

import pandas as pd
import streamlit as st

import common
import theme
from fairsend import cost_model, fx, tuition

theme.header("Compare tuition costs", "Paying a big bill from your home currency? Compare what real banks and "
                                      "services would charge, which is cheapest, and whether the money would arrive "
                                      "before your deadline. FairSend doesn't make the payment; you pay through the "
                                      "bank or service you choose.")

c1, c2, c3 = st.columns([1.1, 1, 1])
amount_due = c1.number_input("Tuition due", min_value=100.0, value=20000.0, step=500.0)
recv_ccy = c2.selectbox("In currency", common.TUITION_CURRENCIES, index=common.TUITION_CURRENCIES.index("USD"))
pay_ccy = c3.selectbox("Paying from", common.TUITION_CURRENCIES, index=common.TUITION_CURRENCIES.index("INR"),
                       help="The currency in your (or your family's) bank account at home")
deadline = st.date_input("Deadline", value=dt.date.today() + dt.timedelta(days=21), min_value=dt.date.today())

if pay_ccy == recv_ccy:
    st.warning("Choose two different currencies.")
    st.stop()
try:
    mid = common.mid_rate(pay_ccy, recv_ccy)
except fx.RateUnavailable as exc:
    st.error(f"We couldn't get today's exchange rate. {exc}")
    st.stop()
real_rate = 1 / mid.rate  # pay-currency units per 1 bill-currency unit, the way people read it

with st.expander("Got a quote from your bank or a payment service? Add it here"):
    st.caption(f"Type what you were offered. Today's real rate is 1 {recv_ccy} = {real_rate:,.2f} {pay_ccy}.")
    quotes = []
    for i, default in enumerate(["My bank", "Payment service"]):
        q1, q2, q3 = st.columns([1.3, 1, 1])
        name = q1.text_input("Name", value=default, key=f"tq_name_{i}")
        rate = q2.number_input(f"Rate ({pay_ccy} per {recv_ccy})", min_value=0.0, value=0.0, format="%.2f",
                               key=f"tq_rate_{i}")
        fee = q3.number_input(f"Fee ({pay_ccy})", min_value=0.0, value=0.0, step=100.0, key=f"tq_fee_{i}")
        q4, q5 = st.columns(2)
        days = q4.number_input("Business days to arrive (if they told you)", min_value=0.0, value=None, step=1.0,
                               key=f"tq_days_{i}")
        deducted = q5.number_input(f"Deducted on arrival ({recv_ccy}, if they told you)", min_value=0.0, value=0.0,
                                   step=5.0, key=f"tq_ded_{i}")
        if rate > 0:
            oriented, _ = cost_model.orient_rate(float(rate), mid.rate)
            if abs(cost_model.markup_pct(oriented, mid.rate)) > 25:
                st.error(f"{name}: that rate is far from today's real rate. Please check it.")
            else:
                quotes.append(tuition.Option(name=name.strip() or f"Quote {i + 1}", kind="quote", markup_pct=None,
                                             provider_rate=oriented, fee_send=float(fee), speed_days=days,
                                             deducted_on_arrival=float(deducted), basis="Your quote"))
    buffer_days = st.number_input("Days your university needs to process a payment (if you know)", min_value=0,
                                  value=0, step=1)

real, scope = tuition.real_options(pay_ccy, recv_ccy)
result = tuition.evaluate(amount_due, recv_ccy, pay_ccy, deadline, real + quotes, mid_rate=mid,
                          buffer_days=int(buffer_days))
t = result.table
fair = amount_due / mid.rate
LABEL = {"Typical bank transfer": "Bank transfer (worldwide average)",
         "Typical online money transfer service": "Online transfer service (worldwide average)"}

usable = t[~t["deadline_status"].isin(["Too late"])]
best = usable.iloc[0] if not usable.empty else t.iloc[0]
extra = best["total_paid"] - fair
theme.answer(
    "Cheapest option", common.money(best["total_paid"], pay_ccy), unit="total",
    detail=(f"with <b>{html.escape(LABEL.get(best['option'], best['option']))}</b>. At the real exchange rate with "
            f"no fees, {common.money(amount_due, recv_ccy)} would cost {common.money(fair, pay_ccy)}, so this "
            f"option adds <b>{common.money(extra, pay_ccy)}</b> (about {common.money(best['total_cost_in_target'], recv_ccy)})."),
    good=True,
)
if scope == "pair":
    theme.note(f"These are real banks and services the World Bank recorded converting {pay_ccy} into {recv_ccy}, "
               "with the fee and exchange rate they charged. They were surveyed on transfers of about $500, so the "
               "cost for a bill this size is an estimate. Your own quote is always the most accurate.")
else:
    theme.note(f"The World Bank hasn't surveyed transfers from {pay_ccy} into {recv_ccy}, so these are worldwide "
               "averages of real bank and online-service prices. Add your bank's quote above for an exact answer.")

ARRIVAL = {"On time": "arrives in time", "Tight": "cutting it close", "Too late": "may miss the deadline",
           "Unknown": "arrival time not given"}
st.subheader("Your options")
theme.option_list([
    {"title": LABEL.get(r["option"], r["option"]),
     "subtitle": f"{'Your quote' if r['kind'] == 'quote' else 'Real World Bank price'} · "
                 f"hidden cost {r['markup_pct']:.2f}% · {ARRIVAL[r['deadline_status']]}",
     "tag": "Cheapest" if r["option"] == best["option"] else ("Late" if r["deadline_status"] == "Too late" else ""),
     "tag_warn": r["deadline_status"] == "Too late",
     "right": common.money(r["total_paid"], pay_ccy),
     "right_sub": "" if r["extra_vs_cheapest"] < 0.5 else f"{common.money(r['extra_vs_cheapest'], pay_ccy)} more"}
    for _, r in t.iterrows()
])
theme.note(f"You have {result.business_days_left} business days before the deadline.")

with st.expander("Where each number comes from"):
    view = pd.DataFrame({"Option": [LABEL.get(o, o) for o in t["option"]],
                         f"You pay ({pay_ccy})": t["total_paid"].round(0),
                         f"Fee ({pay_ccy})": t["fee"].round(0),
                         "Hidden cost in the rate": t["markup_pct"].map(lambda m: f"{m:.2f}%"),
                         "Arrives in": t["speed_days"].map(lambda d: "not given" if pd.isna(d) else
                                                           ("under a day" if d < 1 else f"{d:g} business days")),
                         "Source": t["basis"]})
    st.dataframe(view, hide_index=True, use_container_width=True,
                 column_config={f"You pay ({pay_ccy})": st.column_config.NumberColumn(format="localized")})
    theme.note(f"Real exchange rate: {html.escape(mid.source)}, {mid.rate_date}.")
