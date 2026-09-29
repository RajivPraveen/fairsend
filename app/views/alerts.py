import plotly.graph_objects as go
import streamlit as st

import common
import theme
from fairsend import db, fx
from fairsend.alerts import notify, store

P = theme.palette()
theme.header("Rate alerts", "Exchange rates change every day. Tell us a rate you'd be happy with, and we'll email you "
                            "when it gets there, so you know when to send.")

src, dst, route = common.route_picker("alert")
send_ccy, local_ccy = route["send_currency"], route["country_currency"]
try:
    rate = common.mid_rate(send_ccy, local_ccy)
    hist = common.rate_history(send_ccy, local_ccy, 90)
except fx.RateUnavailable:
    st.error("We couldn't get the exchange rate for this route right now.")
    st.stop()
ctx = fx.range_context(hist, rate.rate)

theme.answer("Today", f"1 {send_ccy} = {rate.rate:,.2f} {local_ccy}",
             detail=(f"Over the last 3 months it ranged from {ctx['low']:,.2f} to {ctx['high']:,.2f}."
                     if ctx else ""))

lo = float(min(ctx.get("low", rate.rate), rate.rate)) * 0.98
hi = float(max(ctx.get("high", rate.rate), rate.rate)) * 1.02
step = 0.0001 if rate.rate < 1 else 0.01 if rate.rate < 100 else 10 ** (len(str(int(rate.rate))) - 4)
target = st.slider(f"Email me when 1 {send_ccy} is worth at least", min_value=lo, max_value=hi,
                   value=min(max(rate.rate * 1.01, lo), hi), step=float(step), format="%.2f")

if len(hist) > 2:
    fig = go.Figure()
    fig.add_scatter(x=hist["date"], y=hist["rate"], line=dict(color=P["s_third"], width=2),
                    hovertemplate="%{x|%b %d}: %{y:,.2f}<extra></extra>")
    fig.add_hline(y=target, line_color=P["accent"], line_width=2, line_dash="dash",
                  annotation_text=f"your target {target:,.2f}", annotation_position="top left")
    fig.update_layout(height=240, showlegend=False, yaxis_range=[lo, hi], margin=dict(t=10))
    theme.chart(fig)
    reached = int((hist["rate"] >= target).sum())
    theme.note(f"In the last 3 months the rate reached this on {reached} of {len(hist)} days. That's history, "
               "not a prediction.")

with st.form("new_alert", border=False):
    email = st.text_input("Your email", placeholder="you@university.edu")
    create = st.form_submit_button("Create alert", type="primary")
if create:
    try:
        with db.session() as conn:
            a = store.create(conn, channel="email", contact=email, send_currency=send_ccy, receive_currency=local_ccy,
                             target_rate=float(target), direction="at_least", source_code=src, dest_code=dst)
    except ValueError as exc:
        st.error(str(exc))
    else:
        st.success(f"Done. We'll email {email} when 1 {send_ccy} reaches {target:,.2f} {local_ccy}.")
        st.markdown("Keep this code. You'll need it to change or delete the alert (there's no account):")
        st.code(a.manage_token, language=None)
        if not notify.channel_configured("email"):
            theme.note("Email isn't set up on this computer yet, so alerts are saved to the data/outbox folder.")
theme.note("We only store your email, the two currencies and your target rate. Delete the alert and it's all gone.")

with st.expander("Change or delete an alert"):
    with st.form("find_alerts", border=False):
        contact_q = st.text_input("Your email")
        token_q = st.text_input("Your code", type="password")
        find = st.form_submit_button("Show my alerts")
    if find:
        st.session_state["alert_owner"] = (contact_q.strip(), token_q.strip())
    owner = st.session_state.get("alert_owner")
    if owner:
        with db.session() as conn:
            mine = store.list_for_contact(conn, *owner)
        if not mine:
            st.warning("No alerts match that email and code.")
        for a in mine:
            with st.container(border=True):
                st.markdown(f"**{a.description}**  \n{'Active' if a.active else 'Paused'} · "
                            f"last sent {(a.last_triggered_at or 'never')[:10]}")
                c1, c2, c3 = st.columns(3)
                with db.session() as conn:
                    token = conn.execute("SELECT manage_token FROM alerts WHERE alert_id=?", (a.alert_id,)).fetchone()[0]
                    if c1.button("Resume" if not a.active else "Pause", key=f"p_{a.alert_id}"):
                        store.update(conn, a.alert_id, token, active=0 if a.active else 1)
                        st.rerun()
                    if c2.button("Delete", key=f"d_{a.alert_id}"):
                        store.delete(conn, a.alert_id, token)
                        st.rerun()
