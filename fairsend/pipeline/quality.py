"""Data quality checks for cleaned RPW rows.

Each check marks failing rows with a flag. Checks with severity "error" also mark rows invalid, which
excludes them from cost comparisons and analysis. "warning" rows are kept but carry the flag, so the
app can explain them (for example, a provider that did not disclose its exchange rate).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

TOLERANCE_PCT = 0.5   # allowed gap between published and recomputed percentages (rounding in the source)


@dataclass(frozen=True)
class Check:
    name: str
    severity: str  # "error" | "warning"
    description: str
    fails: Callable[[pd.DataFrame], pd.Series]


def _recomputed_total(df: pd.DataFrame, n: str) -> pd.Series:
    return df[f"fee{n}_lcu"] / df[f"amt{n}_lcu"] * 100 + df[f"margin{n}_pct"]


def _recomputed_margin(df: pd.DataFrame, n: str) -> pd.Series:
    return (df["interbank_fx"] - df[f"fx_rate{n}"]) / df["interbank_fx"] * 100


CHECKS: list[Check] = [
    Check("duplicate_id", "error", "World Bank service id appears more than once in a sheet",
          lambda d: d["obs_id"].duplicated(keep="first")),
    Check("missing_key_fields", "error", "Period, corridor, provider, or sending currency is missing",
          lambda d: d[["period_date", "source_code", "dest_code", "firm_raw", "send_currency"]].isna().any(axis=1)
          | (d["send_currency"] == "")),
    Check("missing_200_cost", "error", "Fee, amount, or FX margin missing for the $200 transfer",
          lambda d: d[["amt200_lcu", "fee200_lcu", "margin200_pct", "fx_rate200"]].isna().any(axis=1)),
    Check("nonpositive_amount", "error", "Amount sent is zero or negative",
          lambda d: (d["amt200_lcu"] <= 0) | (d["amt500_lcu"] <= 0)),
    Check("negative_fee", "error", "Fee is negative",
          lambda d: (d["fee200_lcu"] < 0) | (d["fee500_lcu"] < 0)),
    Check("nonpositive_rate", "error", "Provider or interbank exchange rate is zero or negative",
          lambda d: (d["interbank_fx"] <= 0) | (d["fx_rate200"] <= 0)),
    Check("impossible_total_cost", "error", "Total cost above 100% or below -10% of the amount sent",
          lambda d: (d["total200_pct"] > 100) | (d["total200_pct"] < -10)
          | (d["total500_pct"] > 100) | (d["total500_pct"] < -10)),
    Check("implausible_fx_margin", "error", "Provider rate more than 10% better or 50% worse than interbank",
          lambda d: (d["margin200_pct"] < -10) | (d["margin200_pct"] > 50)
          | (d["margin500_pct"] < -10) | (d["margin500_pct"] > 50)),
    Check("unknown_receive_currency", "error", "Receiving country has no currency mapping",
          lambda d: d["receive_currency"].isna() | (d["receive_currency"] == "")),
    Check("total_cost_inconsistent", "warning", "Published total cost differs from fee + margin by >0.5 points",
          lambda d: (_recomputed_total(d, "200") - d["total200_pct"]).abs() > TOLERANCE_PCT),
    Check("margin_inconsistent", "warning", "Published FX margin differs from rate vs interbank by >0.5 points",
          lambda d: ((_recomputed_margin(d, "200") - d["margin200_pct"]).abs() > TOLERANCE_PCT) & (d["transparent"] == 1)),
    Check("non_transparent", "warning", "Provider did not disclose its rate; the recorded 0% margin is not a real 0%",
          lambda d: d["transparent"] != 1),
    Check("negative_fx_margin", "warning", "Provider rate better than interbank (promotional or data issue)",
          lambda d: (d["margin200_pct"] < 0) & (d["margin200_pct"] >= -10)),
    Check("missing_500_cost", "warning", "Only the $200 price was collected",
          lambda d: d[["amt500_lcu", "fee500_lcu", "margin500_pct"]].isna().any(axis=1)),
    Check("nonstandard_currency_code", "warning", "Sending currency code was not ISO 4217 (e.g. 'CFA') and was fixed",
          lambda d: d["send_currency_fixed"].astype(bool)),
    Check("unknown_speed", "warning", "Delivery speed missing or not a known category",
          lambda d: d["speed_days_max"].isna()),
    Check("interbank_vs_ecb", "warning", "World Bank interbank rate differs from the ECB rate that day by >5%",
          lambda d: (d["ecb_mid_rate"].notna())
          & ((d["interbank_fx"] - d["ecb_mid_rate"]).abs() / d["ecb_mid_rate"] > 0.05)),
]


def run_checks(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Return (df with quality_flags / is_valid, list of per-check results)."""
    df = df.copy()
    if "ecb_mid_rate" not in df:
        df["ecb_mid_rate"] = np.nan
    flags = pd.Series([[] for _ in range(len(df))], index=df.index)
    invalid = pd.Series(False, index=df.index)
    results = []
    for check in CHECKS:
        failed = check.fails(df).fillna(False).astype(bool)
        for i in df.index[failed]:
            flags[i].append(check.name)
        if check.severity == "error":
            invalid |= failed
        n = len(df)
        results.append({
            "check_name": check.name, "severity": check.severity, "description": check.description,
            "rows_checked": n, "rows_failed": int(failed.sum()),
            "pass_rate": round(1 - failed.sum() / n, 6) if n else 1.0,
        })
    df["quality_flags"] = flags.map(",".join)
    df["is_valid"] = (~invalid).astype(int)
    return df, results
