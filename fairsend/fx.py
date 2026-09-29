"""Mid-market exchange rates.

Primary source: Frankfurter (European Central Bank reference rates, ~30 currencies, daily since 1999).
Fallback: the open fawazahmed0 currency API (200+ currencies, daily since March 2024), used for
currencies the ECB does not publish, such as NGN, PKR, BDT or KES.
Last resort: the interbank rate the World Bank recorded for the corridor in its latest survey.

All fetched rates are cached in the fx_rates table, so repeated lookups are free and offline use works.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

import pandas as pd
import requests

from fairsend import db

FRANKFURTER = "https://api.frankfurter.app"
FALLBACK_URLS = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date}/v1/currencies/{base}.json",
    "https://{date}.currency-api.pages.dev/v1/currencies/{base}.json",
)
FALLBACK_START = dt.date(2024, 3, 2)
TIMEOUT = 20

# Published by the ECB and therefore available from Frankfurter.
ECB_CURRENCIES = frozenset(
    "AUD BGN BRL CAD CHF CNY CZK DKK EUR GBP HKD HUF IDR ILS INR ISK JPY KRW MXN MYR "
    "NOK NZD PHP PLN RON SEK SGD THB TRY USD ZAR".split()
)


class RateUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Rate:
    base: str
    quote: str
    rate: float           # quote units per 1 base unit
    rate_date: dt.date    # the date the rate actually applies to (may precede the requested date)
    source: str


def _today() -> dt.date:
    return dt.date.today()


def _as_date(value: dt.date | str | None) -> dt.date:
    if value is None:
        return _today()
    if isinstance(value, str):
        return dt.date.fromisoformat(value[:10])
    if isinstance(value, dt.datetime):
        return value.date()
    return value


def _cache_put(conn: sqlite3.Connection, rows: list[tuple[str, str, str, float, str]]) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    conn.executemany(
        "INSERT OR REPLACE INTO fx_rates (rate_date, base, quote, rate, source, fetched_at) VALUES (?,?,?,?,?,?)",
        [(*r, now) for r in rows],
    )
    conn.commit()


def _cache_get(conn: sqlite3.Connection, base: str, quote: str, on: dt.date, lookback_days: int = 5) -> Rate | None:
    """Most recent cached rate on or before `on` (weekends and holidays have no ECB fixing)."""
    row = conn.execute(
        "SELECT rate_date, rate, source FROM fx_rates WHERE base=? AND quote=? AND rate_date<=? AND rate_date>=? "
        "ORDER BY rate_date DESC LIMIT 1",
        (base, quote, on.isoformat(), (on - dt.timedelta(days=lookback_days)).isoformat()),
    ).fetchone()
    if row:
        return Rate(base, quote, row["rate"], dt.date.fromisoformat(row["rate_date"]), row["source"])
    return None


def _fresh_latest(conn: sqlite3.Connection, base: str, quote: str, max_age_hours: int = 6) -> Rate | None:
    """A 'latest' rate fetched recently enough to reuse without another network call."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=max_age_hours)).isoformat(timespec="seconds")
    row = conn.execute(
        "SELECT rate_date, rate, source FROM fx_rates WHERE base=? AND quote=? AND fetched_at>=? "
        "AND rate_date>=? ORDER BY rate_date DESC LIMIT 1",
        (base, quote, cutoff, (_today() - dt.timedelta(days=4)).isoformat()),
    ).fetchone()
    if row:
        return Rate(base, quote, row["rate"], dt.date.fromisoformat(row["rate_date"]), row["source"])
    return None


def _fetch_frankfurter(base: str, quote: str, on: dt.date | None) -> Rate:
    path = "latest" if on is None or on >= _today() else on.isoformat()
    r = requests.get(f"{FRANKFURTER}/{path}", params={"from": base, "to": quote}, timeout=TIMEOUT)
    r.raise_for_status()
    body = r.json()
    return Rate(base, quote, float(body["rates"][quote]), dt.date.fromisoformat(body["date"]), "ECB via Frankfurter")


def _fetch_fallback(base: str, quote: str, on: dt.date | None) -> Rate:
    if on is not None and on < FALLBACK_START:
        raise RateUnavailable(f"No daily source for {base}/{quote} before {FALLBACK_START}")
    date_key = "latest" if on is None or on >= _today() else on.isoformat()
    last_error: Exception | None = None
    for template in FALLBACK_URLS:
        url = template.format(date=date_key, base=base.lower())
        try:
            r = requests.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            body = r.json()
            value = body[base.lower()].get(quote.lower())
            if value is None:
                raise RateUnavailable(f"{quote} not published by fallback source")
            return Rate(base, quote, float(value), dt.date.fromisoformat(body["date"]), "fawazahmed0 currency-api")
        except (requests.RequestException, KeyError, ValueError) as exc:
            last_error = exc
    raise RateUnavailable(f"Fallback source failed for {base}/{quote}: {last_error}")


def _world_bank_interbank(conn: sqlite3.Connection, base: str, quote: str, on: dt.date) -> Rate | None:
    row = conn.execute(
        "SELECT collected_date, interbank_fx FROM rpw_prices WHERE send_currency=? AND receive_currency=? "
        "AND is_valid=1 AND collected_date<=? AND interbank_fx>0 ORDER BY collected_date DESC LIMIT 1",
        (base, quote, on.isoformat()),
    ).fetchone()
    if row and row["collected_date"]:
        return Rate(base, quote, row["interbank_fx"], dt.date.fromisoformat(row["collected_date"]),
                    "World Bank interbank rate (survey date)")
    return None


def get_rate(base: str, quote: str, on: dt.date | str | None = None,
             conn: sqlite3.Connection | None = None, allow_world_bank: bool = True) -> Rate:
    """Mid-market rate for `base` -> `quote` on a date (default: latest available)."""
    base, quote = base.upper(), quote.upper()
    target = _as_date(on)
    if base == quote:
        return Rate(base, quote, 1.0, target, "identity")
    own = conn is None
    conn = conn or db.connect()
    try:
        cached = _fresh_latest(conn, base, quote) if on is None else _cache_get(conn, base, quote, target)
        if cached:
            return cached
        fetchers = []
        if base in ECB_CURRENCIES and quote in ECB_CURRENCIES:
            fetchers.append(_fetch_frankfurter)
        fetchers.append(_fetch_fallback)
        errors = []
        for fetch in fetchers:
            try:
                rate = fetch(base, quote, None if on is None else target)
                _cache_put(conn, [(rate.rate_date.isoformat(), base, quote, rate.rate, rate.source)])
                return rate
            except (requests.RequestException, RateUnavailable, KeyError, ValueError) as exc:
                errors.append(f"{fetch.__name__}: {exc}")
        # Offline or unsupported: use the newest cached value within two weeks, then World Bank survey rate.
        stale = _cache_get(conn, base, quote, target, lookback_days=14)
        if stale:
            return stale
        if allow_world_bank:
            wb = _world_bank_interbank(conn, base, quote, target)
            if wb:
                return wb
        raise RateUnavailable(f"No rate for {base}/{quote} on {target}: {'; '.join(errors)}")
    finally:
        if own:
            conn.close()


def get_history(base: str, quote: str, start: dt.date | str, end: dt.date | str | None = None,
                conn: sqlite3.Connection | None = None, fallback_step_days: int = 7) -> pd.DataFrame:
    """Daily mid-market history as a DataFrame[date, rate]. ECB pairs are daily; others are sampled."""
    base, quote = base.upper(), quote.upper()
    start_d, end_d = _as_date(start), _as_date(end)
    own = conn is None
    conn = conn or db.connect()
    try:
        if base in ECB_CURRENCIES and quote in ECB_CURRENCIES:
            try:
                r = requests.get(f"{FRANKFURTER}/{start_d}..{end_d}", params={"from": base, "to": quote},
                                 timeout=TIMEOUT)
                r.raise_for_status()
                rows = [(d, base, quote, float(v[quote]), "ECB via Frankfurter") for d, v in r.json()["rates"].items()]
                _cache_put(conn, rows)
            except requests.RequestException:
                pass  # fall through to whatever is cached
        else:
            day = max(start_d, FALLBACK_START)
            while day <= end_d:
                if _cache_get(conn, base, quote, day, lookback_days=0) is None:
                    try:
                        rate = _fetch_fallback(base, quote, day)
                        _cache_put(conn, [(rate.rate_date.isoformat(), base, quote, rate.rate, rate.source)])
                    except RateUnavailable:
                        pass
                day += dt.timedelta(days=fallback_step_days)
            try:
                get_rate(base, quote, None, conn=conn, allow_world_bank=False)
            except RateUnavailable:
                pass
        df = pd.read_sql_query(
            "SELECT rate_date AS date, rate FROM fx_rates WHERE base=? AND quote=? AND rate_date BETWEEN ? AND ? "
            "ORDER BY rate_date",
            conn, params=(base, quote, start_d.isoformat(), end_d.isoformat()),
        )
        df["date"] = pd.to_datetime(df["date"])
        return df
    finally:
        if own:
            conn.close()


def backfill_ecb_pairs(conn: sqlite3.Connection, pairs: set[tuple[str, str]], start: str, end: str) -> int:
    """Load full daily ECB history for every (base, quote) pair both sides of which the ECB publishes."""
    by_base: dict[str, set[str]] = {}
    for base, quote in pairs:
        if base != quote and base in ECB_CURRENCIES and quote in ECB_CURRENCIES:
            by_base.setdefault(base, set()).add(quote)
    total = 0
    for base, quotes in sorted(by_base.items()):
        r = requests.get(f"{FRANKFURTER}/{start}..{end}", params={"from": base, "to": ",".join(sorted(quotes))},
                         timeout=60)
        r.raise_for_status()
        rows = [(d, base, q, float(v), "ECB via Frankfurter")
                for d, day_rates in r.json()["rates"].items() for q, v in day_rates.items()]
        _cache_put(conn, rows)
        total += len(rows)
    return total


def refresh_latest(conn: sqlite3.Connection, pairs: set[tuple[str, str]]) -> dict[str, int]:
    """Fetch today's rate for many pairs with one request per base currency. Returns counts by source."""
    by_base: dict[str, set[str]] = {}
    for base, quote in pairs:
        if base != quote:
            by_base.setdefault(base, set()).add(quote)
    counts = {"ecb": 0, "fallback": 0, "missing": 0}
    for base, quotes in sorted(by_base.items()):
        rows = []
        ecb_quotes = sorted(q for q in quotes if base in ECB_CURRENCIES and q in ECB_CURRENCIES)
        if ecb_quotes:
            try:
                r = requests.get(f"{FRANKFURTER}/latest", params={"from": base, "to": ",".join(ecb_quotes)},
                                 timeout=TIMEOUT)
                r.raise_for_status()
                body = r.json()
                rows += [(body["date"], base, q, float(v), "ECB via Frankfurter") for q, v in body["rates"].items()]
                counts["ecb"] += len(body["rates"])
            except requests.RequestException:
                pass
        rest = quotes - {r[2] for r in rows}
        if rest:
            body = None
            for template in FALLBACK_URLS:
                try:
                    resp = requests.get(template.format(date="latest", base=base.lower()), timeout=TIMEOUT)
                    resp.raise_for_status()
                    body = resp.json()
                    break
                except (requests.RequestException, ValueError):
                    continue
            table = body.get(base.lower(), {}) if body else {}
            for q in sorted(rest):
                value = table.get(q.lower())
                if value:
                    rows.append((body["date"], base, q, float(value), "fawazahmed0 currency-api"))
                    counts["fallback"] += 1
                else:
                    counts["missing"] += 1
        _cache_put(conn, rows)
    return counts


def range_context(history: pd.DataFrame, current: float) -> dict:
    """Where today's rate sits in its recent range. Descriptive only, not a forecast."""
    if history.empty:
        return {}
    lo, hi = float(history["rate"].min()), float(history["rate"].max())
    pct = float((history["rate"] <= current).mean() * 100)
    return {
        "low": lo, "high": hi, "mean": float(history["rate"].mean()),
        "percentile": pct, "days": int(len(history)),
        "start": history["date"].min().date(), "end": history["date"].max().date(),
    }
