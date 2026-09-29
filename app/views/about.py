import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common
import theme
from fairsend import db

theme.header("About FairSend", "What FairSend does, where its numbers come from, and what stays private.")
theme.note("FairSend is a comparison tool. It doesn't send, hold or convert money, and it isn't paid by any provider.")

st.subheader("The problem")
st.markdown(common.md(
    "When you send money abroad, you pay in two ways. There's the **fee**, which you can see. Then there's the "
    "**exchange rate**: providers usually give you a worse rate than the real one and keep the difference. That "
    "second cost is rarely shown, and a \"zero fee\" transfer often just moves the cost into the rate."))

st.subheader("Where the numbers come from")
st.markdown(common.md(
    "- **Provider prices**: the World Bank checks what real banks and money transfer services charge on hundreds of "
    "routes, every quarter. FairSend uses all of it: about 254,000 prices since 2011.\n"
    "- **The real exchange rate**: the European Central Bank's daily rate (the rate banks trade at), with an open "
    "data source for currencies the ECB doesn't cover.\n"
    "- **Your estimate**: each provider's fee and exchange-rate gap from the survey, applied to your amount at "
    "today's real rate. It's an estimate, so always check the provider's own quote before paying."))

st.subheader("Privacy")
st.markdown(
    "- Receipts are read on this computer and never saved or uploaded.\n"
    "- Questions are answered by an AI model running on this computer.\n"
    "- Rate alerts store only your email, the two currencies and your target. Deleting an alert removes everything.\n"
    "- No tracking or analytics.")

st.subheader("The big picture")
try:
    h = common.global_numbers()
    c1, c2, c3 = st.columns(3)
    c1.metric("Average cost of sending $200", f"{h['latest_global_avg_pct']:.1f}%", help="World Bank survey, latest quarter")
    c2.metric("UN goal for 2030", "3%")
    c3.metric("Routes that meet the goal", f"{h['corridors_below_3_pct']:.0f}%")
    from fairsend.analysis import global_costs as g

    @st.cache_data(ttl=6 * 3600, show_spinner=False)
    def trend() -> pd.DataFrame:
        return g.global_trend(g.load())

    tr = trend()
    P = theme.palette()
    fig = go.Figure()
    fig.add_scatter(x=tr["period_date"], y=tr["avg_total_pct"], line=dict(color=P["s_hidden"], width=2.5),
                    hovertemplate="%{x|%Y}: %{y:.2f}%<extra></extra>")
    fig.add_hline(y=3, line_dash="dot", line_color=P["muted"], annotation_text="UN goal: 3%")
    fig.update_layout(height=260, showlegend=False, title="Average cost of sending money home, worldwide",
                      yaxis_ticksuffix="%", yaxis_range=[0, 10])
    theme.chart(fig)
    theme.note(f"About {h['markup_share_pct']:.0f}% of that cost is hidden in the exchange rate rather than the fee. "
               "The full analysis is in reports/global_remittance_costs.md.")
except Exception:
    pass

st.subheader("Limits")
st.markdown(
    "- Survey prices are snapshots taken every few months at about $200 and $500. Providers change prices often.\n"
    "- Estimates for large amounts, like tuition, are less certain than for everyday transfers.\n"
    "- This is information, not financial advice.")

with st.expander("Data details"):
    f = common.data_freshness()
    st.write(f"Latest survey: {f.get('period')} (collected up to {f.get('collected')}). "
             f"{f.get('rows_valid', 0):,} of {f.get('rows_in', 0):,} prices passed quality checks.")
    q = db.query_df("SELECT check_name AS \"Check\", severity AS \"Type\", rows_failed AS \"Rows flagged\", "
                    "ROUND(pass_rate * 100, 2) AS \"Pass rate %\" FROM quality_results WHERE run_id = "
                    "(SELECT run_id FROM pipeline_runs WHERE status='success' ORDER BY finished_at DESC LIMIT 1)")
    st.dataframe(q, hide_index=True, use_container_width=True)
    st.caption("Data: World Bank Remittance Prices Worldwide (CC BY 4.0); ECB reference rates via Frankfurter.")
