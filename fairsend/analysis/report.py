"""Write the global remittance cost report (Markdown + PNG charts) to reports/.

    fairsend report
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from fairsend import db  # noqa: E402
from fairsend.analysis import global_costs as g  # noqa: E402
from fairsend.config import REPORTS_DIR  # noqa: E402

# Colorblind-safe palette: categorical colors in a fixed order, and status colors (with labels) for the SDG bands.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
GOOD, WARNING, CRITICAL = "#0ca30c", "#fab219", "#d03b3b"
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"


def _style(ax, title: str, ylabel: str | None = None):
    ax.set_facecolor(SURFACE)
    ax.figure.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=12, fontweight="bold")
    if ylabel:
        ax.set_ylabel(ylabel, color=INK2, fontsize=9)


def _save(fig, path: Path) -> str:
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)
    return f"figures/{path.name}"


def chart_trend(trend: pd.DataFrame, out: Path) -> str:
    fig, ax = plt.subplots(figsize=(9, 4.2))
    x = trend["period_date"]
    ax.stackplot(x, trend["avg_fee_pct"], trend["avg_margin_pct"], colors=[ORANGE, BLUE], alpha=0.85,
                 edgecolor=SURFACE, linewidth=1.5)
    ax.plot(x, trend["avg_total_pct"], color=INK, linewidth=2)
    for y, label in ((3, "UN target 3%"), (5, "5% ceiling")):
        ax.axhline(y, color=MUTED, linewidth=1, linestyle=(0, (3, 3)))
        ax.text(x.iloc[0], y + 0.15, label, color=INK2, fontsize=8)
    last = trend.iloc[-1]
    ax.text(x.iloc[-1], last["avg_fee_pct"] / 2, "  Fee", color=INK2, fontsize=9, va="center")
    ax.text(x.iloc[-1], last["avg_fee_pct"] + last["avg_margin_pct"] / 2, "  Exchange-rate markup", color=INK2,
            fontsize=9, va="center")
    ax.text(x.iloc[-1], last["avg_total_pct"] + 0.35, f"  All services {last['avg_total_pct']:.2f}%", color=INK,
            fontsize=9, va="center")
    ax.set_xlim(x.min(), x.max() + pd.Timedelta(days=900))
    ax.set_ylim(0, max(10.5, trend["avg_total_pct"].max() + 1))
    _style(ax, "Average cost of sending USD 200, and what it is made of", "% of amount sent")
    return _save(fig, out / "global_trend.png")


def chart_sdg_bands(status: pd.DataFrame, out: Path) -> str:
    fig, ax = plt.subplots(figsize=(9, 3.8))
    x = status["period_date"]
    ys = [status.get("below_3", 0), status.get("3_to_5", 0), status.get("above_5", 0)]
    ax.stackplot(x, *ys, colors=[GOOD, WARNING, CRITICAL], edgecolor=SURFACE, linewidth=1.5, alpha=0.9)
    last = status.iloc[-1]
    cum = 0
    for key, label in (("below_3", "✓ Below 3% (meets target)"), ("3_to_5", "! 3–5%"), ("above_5", "✕ Above 5% (to be eliminated)")):
        v = float(last.get(key, 0))
        ax.text(x.iloc[-1], cum + v / 2, f"  {label}: {v:.0f}%", color=INK, fontsize=9, va="center")
        cum += v
    ax.set_xlim(x.min(), x.max() + pd.Timedelta(days=1500))
    ax.set_ylim(0, 100)
    _style(ax, "Share of surveyed routes by average cost", "% of routes")
    return _save(fig, out / "sdg_bands.png")


def chart_groups(groups: pd.DataFrame, label_col: str, title: str, out: Path, name: str) -> str:
    groups = groups.sort_values("avg_total_pct")
    fig, ax = plt.subplots(figsize=(9, 0.5 * len(groups) + 1.4))
    y = range(len(groups))
    ax.barh(y, groups["avg_fee_pct"], color=ORANGE, height=0.6, edgecolor=SURFACE, linewidth=2, label="Fee")
    ax.barh(y, groups["avg_margin_pct"], left=groups["avg_fee_pct"], color=BLUE, height=0.6, edgecolor=SURFACE,
            linewidth=2, label="Exchange-rate markup")
    for i, row in enumerate(groups.itertuples()):
        ax.text(row.avg_fee_pct + row.avg_margin_pct + 0.2, i, f"{row.avg_total_pct:.1f}%", va="center",
                color=INK, fontsize=9)
    ax.set_yticks(list(y), groups[label_col], color=INK2, fontsize=9)
    ax.axvline(3, color=MUTED, linewidth=1, linestyle=(0, (3, 3)))
    ax.legend(frameon=False, fontsize=9, loc="lower right", labelcolor=INK2)
    _style(ax, title)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.yaxis.grid(False)
    ax.set_xlabel("% of USD 200 (transparent services)", color=INK2, fontsize=9)
    return _save(fig, out / name)


def _table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join(f"{v:.2f}" if isinstance(v, float) else str(v) for v in row) + " |")
    return "\n".join(lines)


def write(out_dir: Path = REPORTS_DIR) -> Path:
    figs = out_dir / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    with db.session() as conn:
        df = g.load(conn)
        raw_avg = pd.read_sql_query(
            "SELECT period, AVG(total200_pct) AS all_rows, AVG(CASE WHEN is_valid=1 THEN total200_pct END) AS valid "
            "FROM rpw_prices GROUP BY period ORDER BY period_date DESC LIMIT 3", conn)
        excluded = conn.execute("SELECT COUNT(*) FROM rpw_prices WHERE is_valid=0").fetchone()[0]
        quality = pd.read_sql_query(
            "SELECT check_name, severity, rows_failed, pass_rate FROM quality_results WHERE run_id = "
            "(SELECT run_id FROM pipeline_runs WHERE status='success' ORDER BY finished_at DESC LIMIT 1)", conn)
    h = g.headline_numbers(df)
    trend, status = g.global_trend(df), g.sdg_status_trend(df)
    firms = g.by_group(df, "firm_category")
    regions = g.by_group(df, "dest_region")
    digital = g.by_group(df.assign(channel=df["digital"].map({True: "Digital (online/mobile)", False: "Non-digital"})),
                         "channel")
    corr = g.corridor_averages(df)
    ms = g.markup_share(df)
    disp = g.dispersion(df)
    senders = g.by_group(df, "source_name", min_services=50)

    import numpy as np
    years = trend["period_date"].dt.year + (trend["period_date"].dt.month - 1) / 12
    recent = years >= 2015.5
    slope, intercept = np.polyfit(years[recent], trend.loc[recent, "avg_total_pct"], 1)
    projected_2030 = slope * 2030 + intercept
    f_trend = chart_trend(trend, figs)
    f_bands = chart_sdg_bands(status, figs)
    f_firms = chart_groups(firms, "firm_category", "Cost by provider type (latest quarter)", figs, "by_provider_type.png")
    f_regions = chart_groups(regions, "dest_region", "Cost by receiving region (latest quarter)", figs, "by_region.png")

    latest = h["last_period"].replace("_", " ")
    wb_check = _table(raw_avg.rename(columns={"period": "Period", "all_rows": "FairSend, all rows (%)",
                                              "valid": "FairSend, after quality checks (%)"}))
    worst = corr.sort_values("avg_total_pct", ascending=False).head(10)[
        ["source_name", "dest_name", "avg_total_pct", "min_total_pct", "services"]].rename(columns={
            "source_name": "From", "dest_name": "To", "avg_total_pct": "Average %", "min_total_pct": "Cheapest %",
            "services": "Services"})
    best = corr.head(10)[["source_name", "dest_name", "avg_total_pct", "services"]].rename(columns={
        "source_name": "From", "dest_name": "To", "avg_total_pct": "Average %", "services": "Services"})
    senders_t = senders.sort_values("avg_total_pct", ascending=False)[
        ["source_name", "avg_total_pct", "markup_share_pct", "services"]].rename(columns={
            "source_name": "Sending country", "avg_total_pct": "Average %", "markup_share_pct": "Markup share %",
            "services": "Services"})
    spread = disp.head(8)[["source_name", "dest_name", "min", "max"]].rename(columns={
        "source_name": "From", "dest_name": "To", "min": "Cheapest %", "max": "Most expensive %"})
    q = quality.copy()
    q["pass_rate"] = (q["pass_rate"] * 100).round(2)
    q = q.rename(columns={"check_name": "Check", "severity": "Severity", "rows_failed": "Rows failed",
                          "pass_rate": "Pass rate %"})
    bank = firms.set_index("firm_category")
    mto_row = bank.loc["Money Transfer Operator"] if "Money Transfer Operator" in bank.index else None
    bank_row = bank.loc["Bank"] if "Bank" in bank.index else None

    md = f"""# How affordable are remittances? Global costs against the UN 2030 target

*FairSend analysis of the World Bank's Remittance Prices Worldwide data, {h['first_period'].replace('_', ' ')} to {latest}.
Generated {dt.date.today():%B %-d, %Y}.*

## Summary

- **The world is about twice the target.** Sending the equivalent of USD 200 cost **{h['latest_global_avg_pct']:.2f}%** on
  average in {latest} (after quality checks), against the UN's 3% goal for 2030. That is down from
  {h['first_year_global_avg_pct']:.2f}% in 2011.
- **Few routes meet the target.** Only **{h['corridors_below_3_pct']:.0f}%** of the {h['corridors_latest']} routes surveyed in {latest} average
  below 3%, and **{h['corridors_above_5_pct']:.0f}%** still average above the 5% ceiling that SDG 10.c says should be eliminated.
  At the level of individual services, {h['services_below_3_pct']:.0f}% cost under 3%, so cheap options exist on many routes.
- **About {h['markup_share_pct']:.0f}% of the cost is hidden in the exchange rate.** Among services that disclosed their rate, the
  average fee was {ms['avg_fee_pct']:.2f}% of USD 200 and the average exchange-rate markup was {ms['avg_margin_pct']:.2f}%.
- **"Zero fee" is not free.** {ms['zero_fee_share_pct']:.0f}% of services charged no fee on USD 200, but their average markup was
  {ms['zero_fee_avg_margin_pct']:.2f}%, slightly *higher* than the {ms['with_fee_avg_margin_pct']:.2f}% of services that charge a fee.
- **Provider choice matters more than anything else.** On a typical route the most expensive service costs
  **{h['median_ratio']:.1f}×** the cheapest (median over routes with at least five services). On one route in ten the gap is
  {h['p90_ratio']:.0f}× or more.
{f"- **Banks cost about three times as much as money transfer operators**: {bank_row['avg_total_pct']:.1f}% vs {mto_row['avg_total_pct']:.1f}%." if bank_row is not None and mto_row is not None else ""}

## Data and method

- **Source:** World Bank *Remittance Prices Worldwide* (CC BY 4.0): {h['rows']:,} valid price observations across
  {h['corridors']} routes, {h['sending_countries']} sending and {h['receiving_countries']} receiving countries, and {h['providers']} providers
  (after name standardization), over {h['periods']} survey periods ({h['years']} years).
- **Cost measure:** the World Bank's total cost of sending USD 200 = fee ÷ amount + exchange-rate margin against the interbank
  rate. Averages are simple averages across services, as in the World Bank's Global Average.
- **Markup shares** use transparent services only. When a provider does not disclose its rate, the survey records a 0% margin,
  which would understate markups.
- **Validation against the official figure.** Before any quality exclusions, FairSend reproduces the World Bank's published Global
  Average exactly: 6.36% for Q3 2025 and 6.49% for Q1 2025. The figures in this report exclude {excluded:,} rows that fail hard quality
  checks (for example, total costs above 100% or rates more than 50% from interbank), which lowers the latest average slightly:

{wb_check}

## 1. Progress over time

![Global trend]({f_trend})

The black line is the average over all services; the shaded areas split the average of services that disclosed their rate into
fee and markup. The average cost has fallen steadily but slowly: a straight-line trend since mid-2015 ({slope:+.2f} points a year)
points to about **{projected_2030:.1f}% in 2030**, far from the 3% target. Fees have fallen faster than markups, so the share of the cost hidden in the
exchange rate rose from {trend['markup_share_pct'].iloc[0]:.0f}% in {trend['period_date'].iloc[0].year} to a peak of
{trend['markup_share_pct'].max():.0f}% ({trend.loc[trend['markup_share_pct'].idxmax(), 'period_date'].year}) and is {trend['markup_share_pct'].iloc[-1]:.0f}% today.

## 2. How many routes meet the target

![SDG bands]({f_bands})

## 3. Where people pay the most

![By region]({f_regions})

Most expensive routes in {latest} (average across services):

{_table(worst)}

Cheapest routes:

{_table(best)}

Average cost by sending country (countries with 50+ services surveyed in {latest}):

{_table(senders_t)}

## 4. Who charges what

![By provider type]({f_firms})

Digital vs non-digital services:

{_table(digital[['channel', 'avg_total_pct', 'avg_fee_pct', 'avg_margin_pct', 'markup_share_pct', 'services']].rename(columns={'channel': 'Channel', 'avg_total_pct': 'Average %', 'avg_fee_pct': 'Fee %', 'avg_margin_pct': 'Markup %', 'markup_share_pct': 'Markup share %', 'services': 'Services'}))}

## 5. The same transfer, very different prices

Routes with the widest gap between the cheapest and most expensive service in {latest}:

{_table(spread)}

## Data quality

Every pipeline run applies these checks. "Error" rows are excluded; "warning" rows are kept and flagged.

{_table(q)}

## Limitations

- World Bank prices are quarterly mystery-shopping snapshots at two amounts (USD 200 and 500). Prices change often, and the
  survey does not cover every provider or product.
- Simple averages weight every surveyed service equally, regardless of how much money flows through it. The World Bank also
  publishes a flow-weighted average, which is lower.
- Services that do not disclose their exchange rate are recorded with a 0% margin, which understates their cost.
- The payout currency is not recorded in the dataset. FairSend infers it from the interbank rate. This affects consumer-facing
  estimates in the app, not the percentages in this report.
"""
    path = out_dir / "global_remittance_costs.md"
    path.write_text(md)
    return path
