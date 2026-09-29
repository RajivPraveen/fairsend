"""Provider comparison for a route and amount, plus cost trends over time."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd

from fairsend import cost_model, db, fx

PRODUCT_COLUMNS = [
    "obs_id", "period", "period_date", "collected_date", "source_code", "source_name", "dest_code", "dest_name",
    "provider", "network", "firm_type", "payment_instrument", "access_point", "payout_method",
    "speed_label", "speed_days_max", "send_currency", "receive_currency", "country_currency",
    "amt200_lcu", "fee200_lcu", "fx_rate200", "margin200_pct", "total200_pct",
    "amt500_lcu", "fee500_lcu", "fx_rate500", "margin500_pct", "total500_pct",
    "interbank_fx", "transparent", "note", "quality_flags",
]


def corridors(conn: sqlite3.Connection | None = None) -> pd.DataFrame:
    """Routes with prices in their most recent survey period."""
    sql = """
        WITH latest AS (
            SELECT source_code, dest_code, MAX(period_date) AS period_date
            FROM rpw_prices WHERE is_valid = 1 GROUP BY source_code, dest_code)
        SELECT p.source_code, MAX(p.source_name) AS source_name, p.dest_code, MAX(p.dest_name) AS dest_name,
               MAX(p.send_currency) AS send_currency, MAX(p.country_currency) AS country_currency,
               l.period_date, MAX(p.period) AS period, COUNT(DISTINCT p.provider) AS providers,
               COUNT(*) AS products
        FROM rpw_prices p JOIN latest l USING (source_code, dest_code, period_date)
        WHERE p.is_valid = 1
        GROUP BY p.source_code, p.dest_code
        ORDER BY source_name, dest_name
    """
    if conn is not None:
        return pd.read_sql_query(sql, conn)
    return db.query_df(sql)


def latest_products(source_code: str, dest_code: str, conn: sqlite3.Connection | None = None) -> pd.DataFrame:
    sql = f"""
        SELECT {', '.join(PRODUCT_COLUMNS)} FROM rpw_prices
        WHERE is_valid = 1 AND source_code = ? AND dest_code = ?
          AND period_date = (SELECT MAX(period_date) FROM rpw_prices
                             WHERE is_valid = 1 AND source_code = ? AND dest_code = ?)
    """
    params = (source_code, dest_code, source_code, dest_code)
    df = pd.read_sql_query(sql, conn, params=params) if conn is not None else db.query_df(sql, params)
    # The survey often lists the same product twice (e.g. two agent networks with identical prices).
    key = ["provider", "payment_instrument", "payout_method", "speed_label", "fee200_lcu", "margin200_pct",
           "fee500_lcu", "margin500_pct"]
    return df.drop_duplicates(subset=key).reset_index(drop=True)


@dataclass(frozen=True)
class Comparison:
    table: pd.DataFrame           # ranked products (transparent pricing)
    undisclosed: pd.DataFrame     # products that did not disclose their exchange rate
    mid_rate: fx.Rate             # send -> country currency today
    send_currency: str
    country_currency: str
    amount: float
    period: str
    collected_date: str | None

    @property
    def best(self) -> pd.Series | None:
        return None if self.table.empty else self.table.iloc[0]


def price_products(products: pd.DataFrame, amount: float, mid_rate: float, mode: str = "budget",
                   markup_floor: float | None = None) -> pd.DataFrame:
    """Price every product for `amount` of sending currency at today's mid-market rate.

    The provider's rate today is modelled as today's mid rate less the markup the World Bank observed
    for that product (the markup is the stable part of a provider's pricing; the rate itself moves daily).
    Products paid out in USD/EUR are valued in the receiving country's currency at the mid rate.

    Markups are used exactly as surveyed. A negative markup (a rate better than mid-market, usually a
    promotion) is kept and flagged as `promotional_rate`; pass markup_floor=0 to cap it instead.
    """
    rows = []
    for rec in products.to_dict("records"):
        fee_sched, margin_sched = cost_model.schedules_for(rec)
        fee, fee_extrap = fee_sched.at(amount)
        surveyed_margin, _ = margin_sched.at(amount)
        promo = surveyed_margin < 0
        margin = markup_floor if markup_floor is not None and surveyed_margin < markup_floor else surveyed_margin
        rate = cost_model.provider_rate_from_markup(mid_rate, margin)
        builder = cost_model.cost_from_budget if mode == "budget" else cost_model.cost_from_principal
        try:
            c = builder(amount, fee, rate, mid_rate)
        except ValueError:
            continue  # fee larger than the amount
        rows.append({
            **rec,
            "fee": c.fee, "markup_pct": c.markup_pct, "markup_cost": c.markup_cost,
            "total_cost": c.total_cost, "total_cost_pct": c.total_cost_pct,
            "amount_received": c.amount_received, "received_at_mid": c.received_at_mid,
            "provider_rate_today": rate, "fee_extrapolated": fee_extrap,
            "surveyed_markup_pct": surveyed_margin, "promotional_rate": promo,
            "fixed_fee": fee_sched.fixed_part, "percent_fee": fee_sched.percent_part,
            "markup_share_pct": c.markup_share_pct, "total_paid": c.total_paid,
        })
    return pd.DataFrame(rows)


def compare(source_code: str, dest_code: str, amount: float, *, mode: str = "budget",
            payout_methods: list[str] | None = None, max_days: float | None = None,
            conn: sqlite3.Connection | None = None, mid_rate: fx.Rate | None = None) -> Comparison:
    products = latest_products(source_code, dest_code, conn)
    if products.empty:
        raise LookupError(f"No recent World Bank prices for {source_code} -> {dest_code}")
    send, local = products["send_currency"].iloc[0], products["country_currency"].iloc[0]
    rate = mid_rate or fx.get_rate(send, local, conn=conn)
    if payout_methods:
        pattern = "|".join(payout_methods)
        products = products[products["payout_method"].str.contains(pattern, case=False, na=False)]
    if max_days is not None:
        products = products[products["speed_days_max"].fillna(np.inf) <= max_days]
    transparent = products[products["transparent"] == 1]
    undisclosed = products[products["transparent"] != 1]
    priced = price_products(transparent, amount, rate.rate, mode)
    if not priced.empty:
        sort_key = "amount_received" if mode == "budget" else "total_cost"
        priced = priced.sort_values(sort_key, ascending=(mode != "budget")).reset_index(drop=True)
        priced.insert(0, "rank", np.arange(1, len(priced) + 1))
    und = undisclosed.copy()
    if not und.empty:
        fee_only = [cost_model.schedules_for(r)[0].at(amount)[0] for r in und.to_dict("records")]
        und["fee"] = fee_only
    return Comparison(
        table=priced, undisclosed=und.reset_index(drop=True), mid_rate=rate, send_currency=send,
        country_currency=local, amount=amount, period=products["period"].iloc[0] if len(products) else "",
        collected_date=products["collected_date"].max() if len(products) else None,
    )


def savings_vs(comparison: Comparison, provider: str) -> dict | None:
    """How much more arrives with the best option than with the named provider's best product."""
    t = comparison.table
    if t.empty:
        return None
    mine = t[t["provider"].str.lower() == provider.lower()]
    if mine.empty:
        return None
    mine_best, best = mine.iloc[0], t.iloc[0]
    extra_local = best["amount_received"] - mine_best["amount_received"]
    return {"provider": mine_best["provider"], "best_provider": best["provider"],
            "extra_received": extra_local, "extra_received_send": extra_local / comparison.mid_rate.rate,
            "cost_difference": mine_best["total_cost"] - best["total_cost"]}


# ------------------------------------------------------------------ trends

def corridor_trend(source_code: str, dest_code: str, conn: sqlite3.Connection | None = None) -> pd.DataFrame:
    """Per survey period: average, cheapest, and markup share of the $200 cost on a route."""
    sql = """
        SELECT period, period_date,
               AVG(total200_pct) AS avg_total_pct,
               MIN(total200_pct) AS min_total_pct,
               AVG(fee200_lcu / amt200_lcu * 100) AS avg_fee_pct,
               AVG(margin200_pct) AS avg_margin_pct,
               COUNT(*) AS products, COUNT(DISTINCT provider) AS providers
        FROM rpw_prices
        WHERE is_valid = 1 AND transparent = 1 AND source_code = ? AND dest_code = ?
        GROUP BY period, period_date ORDER BY period_date
    """
    params = (source_code, dest_code)
    return pd.read_sql_query(sql, conn, params=params) if conn is not None else db.query_df(sql, params)


def provider_trend(source_code: str, dest_code: str, top_n: int = 8,
                   conn: sqlite3.Connection | None = None) -> pd.DataFrame:
    """Cheapest $200 total cost % per provider per period, for the providers present most often."""
    sql = """
        SELECT period_date, provider, MIN(total200_pct) AS total_pct
        FROM rpw_prices
        WHERE is_valid = 1 AND transparent = 1 AND source_code = ? AND dest_code = ?
        GROUP BY period_date, provider
    """
    params = (source_code, dest_code)
    df = pd.read_sql_query(sql, conn, params=params) if conn is not None else db.query_df(sql, params)
    keep = df["provider"].value_counts().head(top_n).index
    return df[df["provider"].isin(keep)].sort_values("period_date")
