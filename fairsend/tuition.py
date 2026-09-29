"""Tuition and large-transfer mode.

For a fixed bill (say USD 20,000 due by a deadline), what does each way of paying really cost, and
will it arrive in time? Fees matter less at this size; the exchange-rate markup dominates.

Everything comes from data or from the user; nothing is assumed:
  * Real providers for the exact currency pair: when the World Bank has surveyed products that convert
    the paying currency into the bill's currency (e.g. Indian banks sending USD), each provider's latest
    recorded markup, fee and speed are used.
  * Otherwise, worldwide medians of real World Bank prices for banks and for online services.
  * Quotes the user enters (their bank's wire rate, a tuition platform's quote), with the arrival time and
    any deductions the user was told about.
The World Bank surveys ~USD 200 and ~USD 500 transfers. For large bills the recorded fee is treated as
flat and the recorded markup is kept, which is an estimate and is labelled as one.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fairsend import cost_model, db, fx

MIN_BENCHMARK_ROWS = 20

RECENT_ROWS_SQL = """
    WITH recent AS (SELECT DISTINCT period_date FROM rpw_prices ORDER BY period_date DESC LIMIT 4)
    SELECT source_name, dest_name, provider, firm_type, access_point, period, period_date, collected_date,
           send_currency, receive_currency, margin500_pct, fee500_lcu, amt500_lcu,
           fee500_lcu * 500.0 / amt500_lcu AS fee500_usd, speed_days_max, speed_label
    FROM rpw_prices
    WHERE is_valid = 1 AND transparent = 1 AND margin500_pct IS NOT NULL
      AND period_date IN (SELECT period_date FROM recent)
"""


@dataclass
class Option:
    name: str
    kind: str                     # "provider" (real, this currency pair) | "benchmark" | "quote"
    markup_pct: float | None      # recorded markup; quotes carry provider_rate instead
    fee_send: float               # paying currency
    speed_days: float | None      # business days; None = unknown
    provider_rate: float | None = None
    deducted_on_arrival: float = 0.0
    basis: str = ""
    notes: list[str] = field(default_factory=list)


def business_days_until(deadline: dt.date, today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    if deadline <= today:
        return 0
    return int(np.busday_count(today + dt.timedelta(days=1), deadline + dt.timedelta(days=1)))


def deadline_status(speed_days: float | None, business_days_left: int, buffer_days: int = 0) -> str:
    if speed_days is None:
        return "Unknown"
    if speed_days + buffer_days <= business_days_left:
        return "On time"
    if speed_days <= business_days_left:
        return "Tight"
    return "Too late"


def _category(firm_type: str, access_point: str | None) -> str | None:
    if firm_type.startswith("Bank"):
        return "Bank transfer"
    if firm_type.startswith("Money Transfer") and "Internet" in (access_point or ""):
        return "Online money transfer service"
    return None


def pair_providers(pay_currency: str, receive_currency: str, conn: sqlite3.Connection | None = None) -> list[Option]:
    """Real providers the World Bank recorded converting pay_currency into receive_currency (latest survey each)."""
    sql = RECENT_ROWS_SQL + " AND send_currency = ? AND receive_currency = ?"
    params = (pay_currency, receive_currency)
    df = pd.read_sql_query(sql, conn, params=params) if conn is not None else db.query_df(sql, params)
    if df.empty:
        return []
    df = df.sort_values(["period_date", "margin500_pct", "fee500_lcu"], ascending=[False, True, True])
    options = []
    for provider, g in df.groupby("provider", sort=False):
        latest = g[g["period_date"] == g["period_date"].max()]
        r = latest.iloc[0]  # the provider's cheapest product in its latest survey
        options.append(Option(
            name=provider, kind="provider", markup_pct=float(r["margin500_pct"]), fee_send=float(r["fee500_lcu"]),
            speed_days=None if pd.isna(r["speed_days_max"]) else float(r["speed_days_max"]),
            basis=(f"World Bank survey {r['period'].replace('_', ' ')}: {r['source_name']} → {r['dest_name']}, "
                   f"paid in {receive_currency}, surveyed at about USD 500"),
        ))
    return options


def type_benchmarks(source_code: str | None = None, conn: sqlite3.Connection | None = None) -> pd.DataFrame:
    """Worldwide median markup, fee (USD at the ~USD 500 level), and speed for banks and online services."""
    df = pd.read_sql_query(RECENT_ROWS_SQL, conn) if conn is not None else db.query_df(RECENT_ROWS_SQL)
    df["category"] = [_category(f, a) for f, a in zip(df["firm_type"], df["access_point"])]
    df = df.dropna(subset=["category"])
    out = []
    for category, group in df.groupby("category"):
        out.append({
            "category": category, "scope": "all surveyed routes", "rows": len(group),
            "markup_pct": float(group["margin500_pct"].median()),
            "fee_usd": float(group["fee500_usd"].median()),
            "speed_days": float(group["speed_days_max"].median()),
        })
    return pd.DataFrame(out)


def benchmark_options(pay_currency: str, source_code: str | None = None, *,
                      conn: sqlite3.Connection | None = None, usd_to_pay: float | None = None) -> list[Option]:
    """Worldwide medians of real World Bank prices, priced in the paying currency."""
    bench = type_benchmarks(None, conn)
    if usd_to_pay is None:
        usd_to_pay = fx.get_rate("USD", pay_currency, conn=conn).rate
    return [Option(
        name=f"Typical {row.category.lower()}", kind="benchmark", markup_pct=row.markup_pct,
        fee_send=row.fee_usd * usd_to_pay, speed_days=row.speed_days,
        basis=f"Median of {row.rows:,} real World Bank prices on all surveyed routes (last 4 quarters)",
    ) for row in bench.itertuples()]


def real_options(pay_currency: str, receive_currency: str, conn: sqlite3.Connection | None = None
                 ) -> tuple[list[Option], str]:
    """Real providers for this currency pair if the World Bank has them, else worldwide medians.

    Returns (options, scope) where scope is "pair" or "worldwide".
    """
    pair = pair_providers(pay_currency, receive_currency, conn)
    if pair:
        return pair, "pair"
    return benchmark_options(pay_currency, conn=conn), "worldwide"


@dataclass(frozen=True)
class TuitionResult:
    table: pd.DataFrame
    mid_rate: fx.Rate
    pay_currency: str
    receive_currency: str
    amount_due: float
    business_days_left: int


def evaluate(amount_due: float, receive_currency: str, pay_currency: str, deadline: dt.date,
             options: list[Option], *, mid_rate: fx.Rate | None = None, buffer_days: int = 0,
             today: dt.date | None = None, conn: sqlite3.Connection | None = None) -> TuitionResult:
    """Price every option for delivering `amount_due` and check it against the deadline."""
    rate = mid_rate or fx.get_rate(pay_currency, receive_currency, conn=conn)
    days_left = business_days_until(deadline, today)
    rows = []
    for opt in options:
        provider_rate = opt.provider_rate
        if provider_rate is None:
            provider_rate = cost_model.provider_rate_from_markup(rate.rate, opt.markup_pct or 0.0)
        c = cost_model.cost_to_deliver(amount_due, opt.fee_send, provider_rate, rate.rate, opt.deducted_on_arrival)
        rows.append({
            "option": opt.name, "kind": opt.kind, "basis": opt.basis, "notes": "; ".join(opt.notes),
            "provider_rate": provider_rate, "markup_pct": c.markup_pct, "fee": opt.fee_send,
            "deducted_on_arrival": opt.deducted_on_arrival, "total_paid": c.total_paid,
            "markup_cost": c.markup_cost, "total_cost": c.total_cost, "total_cost_pct": c.total_cost_pct,
            "total_cost_in_target": c.total_cost_in_target, "speed_days": opt.speed_days,
            "deadline_status": deadline_status(opt.speed_days, days_left, buffer_days),
        })
    table = pd.DataFrame(rows)
    if not table.empty:
        table = table.sort_values("total_paid").reset_index(drop=True)
        table["extra_vs_cheapest"] = table["total_paid"] - table["total_paid"].min()
    return TuitionResult(table=table, mid_rate=rate, pay_currency=pay_currency,
                         receive_currency=receive_currency, amount_due=amount_due,
                         business_days_left=days_left)


def headline(result: TuitionResult) -> str | None:
    """One plain sentence about the biggest avoidable cost, in the bill's currency.

    Benchmarks are reference points, not something you can buy, so they are never "chosen": with two or
    more quotes we compare the quotes; with one quote we say how it compares with the typical market.
    """
    t = result.table
    if t.empty:
        return None
    to_target = result.mid_rate.rate
    cur = result.receive_currency
    min_worth = max(1.0, result.amount_due * 0.001)  # below 0.1% of the bill isn't worth a headline
    quotes = t[t["kind"] == "quote"]
    feasible_quotes = quotes[quotes["deadline_status"] != "Too late"]
    benchmarks = t[t["kind"] != "quote"]
    if len(quotes) >= 2 and not feasible_quotes.empty:
        best, worst = feasible_quotes.iloc[0], quotes.iloc[-1]
        saving = (worst["total_paid"] - best["total_paid"]) * to_target
        if best["option"] != worst["option"] and saving >= min_worth:
            return (f"Choosing {best['option']} instead of {worst['option']} saves about "
                    f"{saving:,.0f} {cur} on this payment.")
    if len(quotes) >= 1 and not benchmarks.empty:
        q, b = quotes.iloc[0], benchmarks.iloc[0]
        diff = (q["total_paid"] - b["total_paid"]) * to_target
        if diff >= min_worth:
            return (f"Your cheapest quote ({q['option']}) costs about {diff:,.0f} {cur} more than a "
                    f"{b['option'].lower()}. It may be worth asking for a better rate or getting another quote.")
        if -diff >= min_worth:
            return (f"Your quote from {q['option']} is about {-diff:,.0f} {cur} cheaper than a "
                    f"{b['option'].lower()}. That's a good rate.")
        return None
    if len(benchmarks) >= 2:
        lo, hi = benchmarks.iloc[0], benchmarks.iloc[-1]
        diff = (hi["total_paid"] - lo["total_paid"]) * to_target
        if diff >= min_worth:
            return (f"A {lo['option'].lower()} usually costs about {diff:,.0f} {cur} less than a "
                    f"{hi['option'].lower()} for this payment. Enter real quotes above for an exact comparison.")
    return None
