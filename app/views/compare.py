import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common
import theme
from fairsend import compare, fx, savings

SPEED = {"Less than one hour": "arrives within an hour", "Same day": "arrives the same day",
         "Next day": "arrives the next day", "2 days": "arrives in 2 days", "1-3 days": "arrives in 1–3 days",
         "3-5 days": "arrives in 3–5 days", "6 days or more": "takes 6+ days"}
PAYOUT = {"Bank account": "to a bank account", "Cash pickup": "cash pickup", "Mobile wallet": "to a mobile wallet",
          "Card": "to a card", "Home delivery": "home delivery", "Cash pickup (ATM)": "cash from an ATM"}


def describe(row) -> str:
    payout = ", ".join(PAYOUT.get(p.strip(), p.strip().lower()) for p in str(row["payout_method"]).split(","))
    speed = SPEED.get(row["speed_label"], "") if isinstance(row["speed_label"], str) else ""
    return " · ".join(x for x in (payout[:1].upper() + payout[1:], speed) if x)


theme.header("Compare providers", "Enter an amount and a route. We'll show which provider would get the most money to "
                                  "your family, after every fee and the hidden cost in the exchange rate. FairSend "
                                  "only compares prices; you send the money with the provider you choose.")

amount, src, dst, route = common.transfer_inputs("send")
send_ccy, local_ccy = route["send_currency"], route["country_currency"]


def cost_text(cost: float) -> str:
    if cost < -0.005:
        return f"{common.money(-cost, send_ccy)} better than free"
    return "costs you almost nothing" if cost < 0.5 else f"costs you {common.money(cost, send_ccy)}"


with st.expander("Options: how the money should arrive, and how fast"):
    payouts = st.multiselect("Your family receives it as", ["Bank account", "Cash pickup", "Mobile wallet", "Card"],
                             placeholder="Any way")
    speed = st.radio("It needs to arrive", ["Any time", "Within an hour", "Same day"], horizontal=True)
max_days = {"Any time": None, "Within an hour": 0.0, "Same day": 0.5}[speed]
st.query_params.update(src=src, dst=dst, amount=int(amount))

try:
    comp = common.run_compare(src, dst, amount, tuple(payouts), max_days)
except fx.RateUnavailable as exc:
    st.error(f"We couldn't get today's exchange rate for {send_ccy} to {local_ccy}. {exc}")
    st.stop()
except LookupError:
    st.warning("We don't have prices for this route yet.")
    st.stop()
t = comp.table
if t.empty:
    st.warning("No provider matches those options. Try allowing another way to receive the money.")
    st.stop()

best, worst = t.iloc[0], t.iloc[-1]
gap = best["amount_received"] - worst["amount_received"]
rate = comp.mid_rate.rate

# ------------------------------------------------------------------ the answer
theme.answer(
    "Best option",
    common.money(best["amount_received"], local_ccy), unit="would arrive",
    detail=(f"with <b>{html.escape(best['provider'])}</b> ({html.escape(describe(best).lower())}). "
            f"That's <b>{common.money(gap, local_ccy)} more</b> than the most expensive option, "
            f"{html.escape(worst['provider'])}."
            + (" When the World Bank checked, this provider was offering a rate <b>better than the real exchange "
               "rate</b> (a special offer), so confirm it's still available." if best["promotional_rate"] else "")),
    good=True,
)
theme.note(f"If sending money were free, {common.money(amount, send_ccy)} would be "
           f"{common.money(amount * rate, local_ccy)} at today's real exchange rate (1 {send_ccy} = {rate:,.2f} "
           f"{local_ccy}). Every provider delivers less than that. The difference is what the transfer costs you.")

st.subheader("Top 5 options")
theme.option_list([
    {"title": r["provider"], "subtitle": describe(r) + (" · special offer" if r["promotional_rate"] else ""),
     "tag": "Best" if i == 0 else "",
     "right": common.money(r["amount_received"], local_ccy), "right_sub": cost_text(r["total_cost"])}
    for i, (_, r) in enumerate(t.head(5).iterrows())
])

if not comp.undisclosed.empty:
    u = comp.undisclosed.drop_duplicates(["provider", "payout_method", "speed_label", "fee"])
    with st.expander(f"{u['provider'].nunique()} more provider(s) didn't say what exchange rate they use"):
        st.caption("The World Bank recorded their fee, but they didn't disclose their exchange rate, so the full "
                   "cost and the amount that arrives can't be worked out. They're listed here so nothing is hidden.")
        theme.option_list([
            {"title": r["provider"], "subtitle": describe(r), "right": f"fee {common.money(r['fee'], send_ccy)}",
             "right_sub": "exchange rate not disclosed"} for _, r in u.iterrows()])

# ------------------------------------------------------------------ yearly savings
st.subheader("Do you send this regularly?")
c1, c2 = st.columns(2)
freq = c1.selectbox("How often?", list(savings.FREQUENCIES), index=2)
providers = sorted(t["provider"].unique())
current = c2.selectbox("Which service do you use now?", ["I'm not sure"] + providers)
try:
    s = savings.summarize(src, dst, amount, savings.FREQUENCIES[freq],
                          None if current == "I'm not sure" else current, comparison=comp)
    who = f"with {current}" if current != "I'm not sure" else "with a typical provider"
    if s.yearly_savings > 0.5:
        theme.answer("You could save", common.money(s.yearly_savings, send_ccy), unit="a year",
                     detail=(f"Sending {common.money(amount, send_ccy)} {freq.lower()} {html.escape(who)} costs about "
                             f"<b>{common.money(s.yearly_cost_current, send_ccy)} a year</b>. With "
                             f"{html.escape(s.best_provider)} it would be "
                             + (f"<b>{common.money(-s.yearly_cost_best, send_ccy)} in your favour</b> (its "
                                "special-offer rate beat the real rate)" if s.yearly_cost_best < -0.5 else
                                "<b>almost nothing</b>" if s.yearly_cost_best < 1 else
                                f"about <b>{common.money(s.yearly_cost_best, send_ccy)}</b>")
                             + ", so your family gets "
                             f"{common.money(s.yearly_extra_received, local_ccy)} more each year."))
    else:
        st.success(f"{current} is already the cheapest option for this transfer.")
except LookupError:
    st.info("That service doesn't offer this kind of transfer on this route.")

# ------------------------------------------------------------------ details
with st.expander(f"More details: all {len(t)} options, and where the cost comes from"):
    st.markdown(common.md(
        f"Each transfer has two costs. The **fee** is what the provider charges you openly. The **hidden cost** is "
        f"how much worse their exchange rate is than the real one. On {common.money(amount, send_ccy)}, the best "
        f"option's cost splits like this:"))
    if best["markup_cost"] >= 0:
        theme.cost_bar(best["fee"], best["markup_cost"], f"Fee {common.money(best['fee'], send_ccy)}",
                       f"Hidden in the exchange rate {common.money(best['markup_cost'], send_ccy)}")
    else:
        st.markdown(common.md(f"Fee {common.money(best['fee'], send_ccy)}. Its exchange rate was better than the "
                              f"real one, worth {common.money(-best['markup_cost'], send_ccy)} to you (a special offer)."))
    view = pd.DataFrame({
        "Provider": t["provider"],
        f"Arrives ({local_ccy})": t["amount_received"].round(0),
        f"Total cost ({send_ccy})": t["total_cost"].round(2),
        f"Fee ({send_ccy})": t["fee"].round(2),
        f"Hidden cost ({send_ccy})": t["markup_cost"].round(2),
        "How it arrives": [describe(r) for _, r in t.iterrows()],
    })
    st.dataframe(view, hide_index=True, use_container_width=True, height=min(420, 38 + 35 * len(view)),
                 column_config={f"Arrives ({local_ccy})": st.column_config.NumberColumn(format="localized")})
    st.markdown("**What the World Bank actually recorded** (before we apply today's exchange rate):")
    raw = pd.DataFrame({
        "Provider": t["provider"], "Checked on": t["collected_date"],
        f"Sent ({send_ccy})": t["amt500_lcu"].fillna(t["amt200_lcu"]).round(2),
        f"Fee ({send_ccy})": t["fee500_lcu"].fillna(t["fee200_lcu"]).round(2),
        "Their rate": t["fx_rate500"].fillna(t["fx_rate200"]),
        "Real rate that day": t["interbank_fx"],
        "Hidden cost": t["surveyed_markup_pct"].map(lambda m: f"{m:.2f}%"),
    })
    st.dataframe(raw, hide_index=True, use_container_width=True, height=min(360, 38 + 35 * len(raw)))
    theme.note("Source: World Bank Remittance Prices Worldwide, one row per product surveyed on this route.")
    trend = compare.corridor_trend(src, dst)
    if len(trend) > 1:
        P = theme.palette()
        trend["period_date"] = pd.to_datetime(trend["period_date"])
        fig = go.Figure()
        fig.add_scatter(x=trend["period_date"], y=trend["avg_total_pct"], name="Average provider",
                        line=dict(color=P["s_third"], width=2))
        fig.add_scatter(x=trend["period_date"], y=trend["min_total_pct"], name="Cheapest provider",
                        line=dict(color=P["s_hidden"], width=2))
        fig.update_layout(height=300, title=f"Cost of sending about $200, {route['source_name']} → {route['dest_name']}",
                          yaxis_title="% of the amount sent", yaxis_ticksuffix="%")
        theme.chart(fig)
common.estimates_note(comp.period, comp.collected_date, comp.mid_rate)
