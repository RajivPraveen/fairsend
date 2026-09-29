"""Before/after analysis of the user study, plus alert retention from the FairSend database.

    python research/analyze.py --pre data/research/pre.csv --post data/research/post.csv \
        --study-start 2026-10-15 --weeks 4

Column names follow research/templates/*.csv. Writes research/results.md (aggregates only).
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import pandas as pd

from fairsend import db

HERE = Path(__file__).resolve().parent


def sus_score(row: pd.Series) -> float | None:
    """Standard System Usability Scale: odd items (x-1), even items (5-x), times 2.5."""
    items = [row.get(f"sus_{i}") for i in range(1, 11)]
    if any(pd.isna(v) for v in items):
        return None
    return sum((v - 1) if i % 2 == 0 else (5 - v) for i, v in enumerate(items)) * 2.5


def unaware_of_markup(pre: pd.DataFrame) -> pd.Series:
    """Unaware = didn't tick 'worse exchange rate' as a cost, or believes a no-fee transfer costs nothing."""
    ticked = pre["costs_known"].fillna("").str.contains("exchange rate", case=False)
    quiz_wrong = pre["zero_fee_quiz"].fillna("").str.lower().isin(["true", "not sure"])
    return ~ticked | quiz_wrong


def alert_retention(study_start: dt.date, weeks: int) -> dict:
    """Alerts created in the study's first week; how many are still active N weeks later."""
    end_first_week = study_start + dt.timedelta(days=7)
    with db.session() as conn:
        created = conn.execute("SELECT COUNT(*) FROM alerts WHERE created_at >= ? AND created_at < ?",
                               (study_start.isoformat(), end_first_week.isoformat())).fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM alerts WHERE created_at >= ? AND created_at < ? AND active=1",
                              (study_start.isoformat(), end_first_week.isoformat())).fetchone()[0]
        fired = conn.execute("SELECT COUNT(DISTINCT alert_id) FROM alert_events WHERE status='sent' AND fired_at >= ?",
                             (study_start.isoformat(),)).fetchone()[0]
        daily = pd.read_sql_query("SELECT * FROM alert_daily_stats WHERE stat_date >= ? ORDER BY stat_date", conn,
                                  params=(study_start.isoformat(),))
    # Deleted alerts leave no row; the daily stats table keeps the history of counts.
    return {"created_first_week": created, "still_active_now": active, "alerts_that_fired": fired,
            "weeks": weeks, "daily_active": daily}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pre", type=Path, required=True)
    ap.add_argument("--post", type=Path, required=True)
    ap.add_argument("--study-start", type=dt.date.fromisoformat)
    ap.add_argument("--weeks", type=int, default=4)
    args = ap.parse_args()
    text_cols = {"zero_fee_quiz": str, "zero_fee_quiz_post": str, "costs_known": str, "switched": str, "learned": str}
    pre = pd.read_csv(args.pre, dtype={k: v for k, v in text_cols.items()}, keep_default_na=False, na_values=[""])
    post = pd.read_csv(args.post, dtype={k: v for k, v in text_cols.items()}, keep_default_na=False, na_values=[""])
    both = pre.merge(post, on="code", how="inner")
    n = len(both)
    unaware = unaware_of_markup(both)
    quiz_pre = both["zero_fee_quiz"].fillna("").str.lower().eq("false").mean() * 100
    quiz_post = both["zero_fee_quiz_post"].fillna("").str.lower().eq("false").mean() * 100
    savings = pd.to_numeric(both["est_yearly_saving"], errors="coerce")
    sus = both.apply(sus_score, axis=1).dropna()
    switched = both["switched"].fillna("")
    lines = [
        "# User study results", "",
        f"Participants with both surveys: **{n}**", "",
        "| Measure | Result |", "|---|---|",
        f"| Unaware of hidden exchange-rate markups (before) | {unaware.mean() * 100:.0f}% |",
        f"| Correctly answered \"no-fee transfers cost nothing\" = False | {quiz_pre:.0f}% before → {quiz_post:.0f}% after |",
        f"| Confidence finding good value (1–5), mean | {both['confidence_pre'].mean():.1f} → {both['confidence_post'].mean():.1f} |",
        f"| Learned something new | {both['learned'].fillna('').str.startswith('Yes').mean() * 100:.0f}% |",
        f"| Estimated yearly saving, mean (median) | ${savings.mean():,.0f} (${savings.median():,.0f}) |",
        f"| Intend to change how they send (4–5 of 5) | {(both['intent_switch'] >= 4).mean() * 100:.0f}% |",
        f"| Switched provider by 4 weeks | {switched.eq('Switched provider').mean() * 100:.0f}% |",
        f"| Changed product or payout method | {switched.eq('Changed product or payout method').mean() * 100:.0f}% |",
        f"| System Usability Scale, mean | {sus.mean():.0f} / 100 (n={len(sus)}) |",
        f"| Most useful feature | {both['most_useful'].mode().iat[0] if both['most_useful'].notna().any() else 'n/a'} |",
    ]
    if args.study_start:
        r = alert_retention(args.study_start, args.weeks)
        lines += [
            f"| Rate alerts set in week 1 | {r['created_first_week']} |",
            f"| Still active after {args.weeks} weeks | {r['still_active_now']} "
            f"({(r['still_active_now'] / r['created_first_week'] * 100) if r['created_first_week'] else 0:.0f}%) |",
            f"| Alerts that fired at least once | {r['alerts_that_fired']} |",
        ]
    confusing = both["confusing"].dropna()
    if len(confusing):
        lines += ["", "## What confused people (verbatim, for triage)", ""] + [f"- {c}" for c in confusing]
    out = HERE / "results.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
