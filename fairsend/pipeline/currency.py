"""Infer the currency each product actually pays out in.

The RPW dataset records the sending currency but not the payout currency. Many products pay out in
USD or EUR rather than the receiving country's own currency (USD to the Philippines, EUR to Romania,
USD to China), and some countries changed currency during the coverage period (Lithuania, Latvia,
Croatia). The interbank rate the World Bank recorded tells us which one applied: we compare it with
the ECB reference rate for each candidate currency on the collection date and pick the closest match.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from fairsend.config import REFERENCE_DIR
from fairsend.fx import ECB_CURRENCIES

MATCH_TOLERANCE = 0.05     # candidate must be within 5% of the recorded interbank rate
IDENTITY_TOLERANCE = 0.01  # interbank ~1.0 with a different country currency => paid in the sending currency

# Currencies with a fixed USD peg (units per USD), which lets us test USD payout without ECB data.
USD_PEGS = {"AED": 3.6725, "SAR": 3.75, "QAR": 3.64, "OMR": 0.3845, "BHD": 0.376, "JOD": 0.709,
            "HKD": 7.8, "PAB": 1.0, "XCD": 2.7, "BMD": 1.0}


@lru_cache(maxsize=1)
def legacy_currencies() -> pd.DataFrame:
    df = pd.read_csv(REFERENCE_DIR / "legacy_currencies.csv", comment="#")
    df["until"] = pd.to_datetime(df["until"])
    return df


def country_currency_on(dest_code: pd.Series, dates: pd.Series, current: pd.Series) -> pd.Series:
    """Country currency on each date, applying legacy currencies before a changeover."""
    out = current.copy()
    for row in legacy_currencies().itertuples():
        mask = (dest_code == row.iso3) & (dates <= row.until)
        out[mask] = row.currency
    return out


def _rate_lookup(rates: pd.DataFrame, keys: pd.DataFrame) -> pd.Series:
    """As-of join of (base, quote, date) keys against the ECB table; returns NaN where unknown."""
    left = keys.reset_index().dropna(subset=["_date"]).sort_values("_date")
    if left.empty or rates.empty:
        return pd.Series(np.nan, index=keys.index)
    merged = pd.merge_asof(left, rates, left_on="_date", right_on="rate_date",
                           left_by=["base", "quote"], right_by=["base", "quote"],
                           direction="backward", tolerance=pd.Timedelta(days=5)).set_index("index")
    return merged["rate"].reindex(keys.index)


def _usd_rate(ecb: pd.DataFrame, send: pd.Series, dates: pd.Series) -> pd.Series:
    """send -> USD rate from ECB, or from a USD peg."""
    rate = _rate_lookup(ecb, pd.DataFrame({"base": send, "quote": "USD", "_date": dates}))
    pegged = send.map(USD_PEGS)
    return rate.fillna(1 / pegged)


def infer_receive_currency(df: pd.DataFrame, ecb: pd.DataFrame) -> pd.DataFrame:
    """Add payout_currency, country_currency, and payout_currency_basis columns."""
    df = df.copy()
    dates = pd.to_datetime(df["collected_date"], errors="coerce").fillna(pd.to_datetime(df["period_date"]))
    df["country_currency"] = country_currency_on(df["dest_code"], dates, df["receive_currency"])
    ib = df["interbank_fx"]

    def rel_gap(rate: pd.Series) -> pd.Series:
        return (ib - rate).abs() / rate

    local = _rate_lookup(ecb, pd.DataFrame({"base": df["send_currency"], "quote": df["country_currency"],
                                            "_date": dates}))
    usd = _usd_rate(ecb, df["send_currency"], dates)
    eur = _rate_lookup(ecb, pd.DataFrame({"base": df["send_currency"], "quote": "EUR", "_date": dates}))
    # For EUR we also allow a USD-pegged sender via the USD cross rate.
    usd_eur = _rate_lookup(ecb, pd.DataFrame({"base": pd.Series("USD", index=df.index), "quote": "EUR",
                                              "_date": dates}))
    eur = eur.fillna(usd * usd_eur)

    gaps = pd.DataFrame({
        "local": rel_gap(local),
        "USD": rel_gap(usd).where(df["send_currency"] != "USD"),
        "EUR": rel_gap(eur).where(df["send_currency"] != "EUR"),
    })
    same_as_send = ((ib - 1).abs() <= IDENTITY_TOLERANCE) & (df["send_currency"] != df["country_currency"])

    payout = df["country_currency"].copy()
    basis = pd.Series("country default", index=df.index)
    local_ok = gaps["local"] <= MATCH_TOLERANCE
    basis[local_ok] = "matched ECB rate"
    foreign_gaps = gaps[["USD", "EUR"]].fillna(np.inf)
    best = foreign_gaps.idxmin(axis=1)
    best_gap = foreign_gaps.min(axis=1)
    foreign = ~local_ok & (best_gap <= MATCH_TOLERANCE) & (best_gap < gaps["local"].fillna(np.inf))
    payout[foreign] = best[foreign]
    basis[foreign] = "matched ECB rate"
    payout[same_as_send & ~local_ok] = df.loc[same_as_send & ~local_ok, "send_currency"]
    basis[same_as_send & ~local_ok] = "interbank rate = 1"
    df["receive_currency"] = payout
    df["payout_currency_basis"] = basis
    return df


def ecb_table(conn) -> pd.DataFrame:
    rates = pd.read_sql_query(
        "SELECT rate_date, base, quote, rate FROM fx_rates WHERE source='ECB via Frankfurter'", conn)
    rates["rate_date"] = pd.to_datetime(rates["rate_date"])
    return rates.sort_values("rate_date")


def candidate_pairs(df: pd.DataFrame) -> set[tuple[str, str]]:
    pairs = set()
    for s, c in zip(df["send_currency"], df["receive_currency"]):
        pairs |= {(s, c), (s, "USD"), (s, "EUR")}
    pairs.add(("USD", "EUR"))
    return {p for p in pairs if p[0] in ECB_CURRENCIES and p[1] in ECB_CURRENCIES}
