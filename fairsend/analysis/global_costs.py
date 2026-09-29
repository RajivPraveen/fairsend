"""Global remittance costs measured against UN Sustainable Development Goal target 10.c.

SDG 10.c: by 2030, reduce the transaction costs of migrant remittances to less than 3% and eliminate
remittance corridors with costs higher than 5%. Following World Bank practice, costs are for sending
the equivalent of USD 200, and averages are simple (unweighted) averages across surveyed services.

Markup shares use transparent services only, because a non-transparent service's recorded 0% margin
means "not disclosed", not "no markup".
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from fairsend import db

SDG_TARGET = 3.0
SDG_CORRIDOR_MAX = 5.0


def load(conn: sqlite3.Connection | None = None) -> pd.DataFrame:
    sql = """
        SELECT period, period_date, source_code, source_name, source_region, source_income,
               dest_code, dest_name, dest_region, dest_income, corridor, provider, firm_type,
               payment_instrument, access_point, payout_method, speed_days_max,
               fee200_lcu / amt200_lcu * 100 AS fee_pct, margin200_pct AS margin_pct,
               total200_pct AS total_pct, fee200_lcu, transparent
        FROM rpw_prices WHERE is_valid = 1
    """
    df = pd.read_sql_query(sql, conn) if conn is not None else db.query_df(sql)
    df["period_date"] = pd.to_datetime(df["period_date"])
    df["year"] = df["period_date"].dt.year
    df["firm_category"] = df["firm_type"].str.split(" / ").str[0]
    df["digital"] = df["access_point"].fillna("").str.contains("Internet|Mobile", case=False)
    return df


def coverage(df: pd.DataFrame) -> dict:
    return {
        "rows": len(df), "periods": df["period"].nunique(), "corridors": df["corridor"].nunique(),
        "providers": df["provider"].nunique(), "sending_countries": df["source_code"].nunique(),
        "receiving_countries": df["dest_code"].nunique(),
        "first_period": df.loc[df["period_date"].idxmin(), "period"],
        "last_period": df.loc[df["period_date"].idxmax(), "period"],
        "years": int(df["year"].max() - df["year"].min() + 1),
    }


def global_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Global average total cost per period, and its fee and markup components."""
    t = df[df["transparent"] == 1]
    out = df.groupby("period_date").agg(avg_total_pct=("total_pct", "mean"), services=("total_pct", "size"))
    parts = t.groupby("period_date").agg(avg_fee_pct=("fee_pct", "mean"), avg_margin_pct=("margin_pct", "mean"))
    out = out.join(parts)
    out["markup_share_pct"] = out["avg_margin_pct"] / (out["avg_fee_pct"] + out["avg_margin_pct"]) * 100
    return out.reset_index()


def corridor_averages(df: pd.DataFrame, period_date=None) -> pd.DataFrame:
    latest = df[df["period_date"] == (period_date or df["period_date"].max())]
    g = latest.groupby(["corridor", "source_name", "dest_name", "dest_region"]).agg(
        avg_total_pct=("total_pct", "mean"), min_total_pct=("total_pct", "min"), max_total_pct=("total_pct", "max"),
        services=("total_pct", "size"), providers=("provider", "nunique")).reset_index()
    g["sdg_band"] = pd.cut(g["avg_total_pct"], [-np.inf, SDG_TARGET, SDG_CORRIDOR_MAX, np.inf],
                           labels=["Below 3% (meets target)", "3-5%", "Above 5% (to be eliminated)"])
    return g.sort_values("avg_total_pct")


def sdg_status_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Per period: share of corridors whose average cost is below 3%, 3-5%, above 5%."""
    g = df.groupby(["period_date", "corridor"])["total_pct"].mean().reset_index()
    g["band"] = pd.cut(g["total_pct"], [-np.inf, SDG_TARGET, SDG_CORRIDOR_MAX, np.inf],
                       labels=["below_3", "3_to_5", "above_5"])
    out = g.pivot_table(index="period_date", columns="band", values="corridor", aggfunc="count", observed=False)
    out = out.div(out.sum(axis=1), axis=0) * 100
    return out.reset_index()


def by_group(df: pd.DataFrame, col: str, period_date=None, min_services: int = 20) -> pd.DataFrame:
    latest = df[df["period_date"] == (period_date or df["period_date"].max())]
    t = latest[latest["transparent"] == 1]
    g = latest.groupby(col).agg(avg_total_pct=("total_pct", "mean"), services=("total_pct", "size"))
    parts = t.groupby(col).agg(avg_fee_pct=("fee_pct", "mean"), avg_margin_pct=("margin_pct", "mean"))
    g = g.join(parts)
    g["markup_share_pct"] = g["avg_margin_pct"] / (g["avg_fee_pct"] + g["avg_margin_pct"]) * 100
    return g[g["services"] >= min_services].sort_values("avg_total_pct").reset_index()


def markup_share(df: pd.DataFrame, period_date=None) -> dict:
    """How much of the cost is hidden in the exchange rate, latest period, transparent services."""
    latest = df[(df["period_date"] == (period_date or df["period_date"].max())) & (df["transparent"] == 1)]
    fee, margin = latest["fee_pct"].mean(), latest["margin_pct"].mean()
    zero_fee = latest[latest["fee200_lcu"] == 0]
    with_fee = latest[latest["fee200_lcu"] > 0]
    return {
        "avg_fee_pct": fee, "avg_margin_pct": margin, "markup_share_pct": margin / (fee + margin) * 100,
        "zero_fee_services": len(zero_fee), "zero_fee_share_pct": len(zero_fee) / len(latest) * 100,
        "zero_fee_avg_margin_pct": zero_fee["margin_pct"].mean(),
        "with_fee_avg_margin_pct": with_fee["margin_pct"].mean(),
        "zero_fee_avg_total_pct": zero_fee["total_pct"].mean(),
    }


def dispersion(df: pd.DataFrame, period_date=None, min_services: int = 5) -> pd.DataFrame:
    """Within each corridor: how many times more the most expensive service costs than the cheapest.

    Uses the cost in money terms at USD 200; corridors whose cheapest service costs under 0.25% are
    excluded from the ratio (a near-zero denominator makes the multiple meaningless).
    """
    latest = df[df["period_date"] == (period_date or df["period_date"].max())]
    g = latest.groupby(["corridor", "source_name", "dest_name"])["total_pct"].agg(["min", "max", "size"]).reset_index()
    g = g[(g["size"] >= min_services)]
    g["spread_pts"] = g["max"] - g["min"]
    g["ratio"] = np.where(g["min"] >= 0.25, g["max"] / g["min"].where(g["min"] >= 0.25), np.nan)
    return g.sort_values("spread_pts", ascending=False)


def headline_numbers(df: pd.DataFrame) -> dict:
    latest_date = df["period_date"].max()
    latest = df[df["period_date"] == latest_date]
    corr = corridor_averages(df)
    disp = dispersion(df)
    trend = global_trend(df)
    first_year = trend[trend["period_date"].dt.year == trend["period_date"].dt.year.min()]
    ms = markup_share(df)
    return {
        **coverage(df),
        "latest_global_avg_pct": latest["total_pct"].mean(),
        "first_year_global_avg_pct": first_year["avg_total_pct"].mean(),
        "services_below_3_pct": (latest["total_pct"] < SDG_TARGET).mean() * 100,
        "corridors_below_3_pct": (corr["avg_total_pct"] < SDG_TARGET).mean() * 100,
        "corridors_above_5_pct": (corr["avg_total_pct"] > SDG_CORRIDOR_MAX).mean() * 100,
        "corridors_latest": len(corr),
        "median_ratio": float(disp["ratio"].median()),
        "p90_ratio": float(disp["ratio"].quantile(0.9)),
        "median_spread_pts": float(disp["spread_pts"].median()),
        "markup_share_pct": ms["markup_share_pct"],
        "zero_fee_avg_margin_pct": ms["zero_fee_avg_margin_pct"],
        "with_fee_avg_margin_pct": ms["with_fee_avg_margin_pct"],
        "zero_fee_share_pct": ms["zero_fee_share_pct"],
    }
