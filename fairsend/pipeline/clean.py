"""Standardize provider names, categories, dates, and currencies in raw RPW rows."""

from __future__ import annotations

import re
from functools import lru_cache

import numpy as np
import pandas as pd

from fairsend.config import REFERENCE_DIR

# ---------------------------------------------------------------- providers

_LEGAL_SUFFIX = re.compile(
    r"\b(ltd|limited|inc|llc|plc|s ?a|sa de cv|co|corp|corporation|company|gmbh|ag|bv|nv|spa|srl|the)\b"
)
_VIA = re.compile(r"^(?P<agent>.+?)\s+via\s+(?P<network>.+)$", re.IGNORECASE)
_NETWORK_IN_PARENS = re.compile(r"\((?P<network>western union|moneygram|ria)\)", re.IGNORECASE)


def provider_key(name: str) -> str:
    """Matching key that ignores case, punctuation, legal suffixes, and parenthetical qualifiers."""
    s = name.lower().replace("&", " and ").replace("'", "")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = _LEGAL_SUFFIX.sub(" ", s)
    return re.sub(r"\s+", "", s)


@lru_cache(maxsize=1)
def _aliases() -> dict[str, str]:
    path = REFERENCE_DIR / "provider_aliases.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, comment="#")
    return {provider_key(a): c for a, c in zip(df["alias"], df["canonical"])}


def standardize_providers(firm_raw: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Return (provider, network). The display name for each key is its most frequent spelling."""
    raw = firm_raw.fillna("Unknown").astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    keys = raw.map(provider_key)
    canonical = (
        pd.DataFrame({"k": keys, "name": raw}).value_counts().reset_index()
        .drop_duplicates("k").set_index("k")["name"]
    )
    aliases = _aliases()
    provider = keys.map(lambda k: aliases.get(k) or canonical[k])

    def network_of(name: str) -> str | None:
        m = _VIA.match(name) or _NETWORK_IN_PARENS.search(name)
        if m:
            net = m.group("network").strip()
            return aliases.get(provider_key(net), net)
        return None

    network = raw.map(network_of)
    network = network.where(network.notna(), provider)
    return provider, network


# ---------------------------------------------------------------- categories

FIRM_TYPES = {
    "money transfer operator": "Money Transfer Operator",
    "bank": "Bank",
    "post office": "Post office",
    "mobile operator": "Mobile Operator",
    "non-bank fi": "Non-bank FI",
    "credit union": "Credit union",
    "building society": "Building society",
}


def standardize_firm_type(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "Unknown"
    parts = [p.strip().lower() for p in value.split("/")]
    return " / ".join(FIRM_TYPES.get(p, p.title()) for p in parts)


def firm_category(firm_type: str) -> str:
    """Primary type used for grouping: the first listed type."""
    return firm_type.split(" / ")[0]


# Upper bound on delivery time in business days after sending.
SPEED_DAYS = {
    "less than one hour": 0.0,
    "same day": 0.5,
    "next day": 1.0,
    "2 days": 2.0,
    "1-3 days": 3.0,
    "3-5 days": 5.0,
    "6 days or more": 7.0,
}
SPEED_LABELS = {
    "less than one hour": "Less than one hour", "same day": "Same day", "next day": "Next day",
    "2 days": "2 days", "1-3 days": "1-3 days", "3-5 days": "3-5 days", "6 days or more": "6 days or more",
}

_PAYOUT_TOKENS = [
    (re.compile(r"atm"), "Cash pickup (ATM)"),
    (re.compile(r"cash"), "Cash pickup"),
    (re.compile(r"bank|account"), "Bank account"),
    (re.compile(r"mobile|wallet"), "Mobile wallet"),
    (re.compile(r"card"), "Card"),
    (re.compile(r"home|door"), "Home delivery"),
]


def standardize_payout(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "Unknown"
    found: list[str] = []
    for part in value.split(","):
        p = part.strip().lower()
        for pattern, label in _PAYOUT_TOKENS:
            if pattern.search(p):
                if label not in found:
                    found.append(label)
                break
    return ", ".join(found) if found else value.strip()


def tidy_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    v = re.sub(r"\s*,\s*", ", ", value.strip())
    return v or None


# ---------------------------------------------------------------- dates and currencies

def period_to_date(period: pd.Series) -> pd.Series:
    """'2025_3Q' -> 2025-07-01."""
    m = period.astype(str).str.extract(r"^(\d{4})_(\d)Q$")
    year = pd.to_numeric(m[0], errors="coerce")
    q = pd.to_numeric(m[1], errors="coerce")
    return pd.to_datetime(dict(year=year, month=(q - 1) * 3 + 1, day=1), errors="coerce")


def parse_collected(value: pd.Series) -> pd.Series:
    as_text = value.map(lambda v: v if isinstance(v, str) else None)
    parsed = pd.to_datetime(as_text, format="%d/%b/%Y", errors="coerce")
    native = pd.to_datetime(value.map(lambda v: None if isinstance(v, str) else v), errors="coerce")
    return parsed.fillna(native)


@lru_cache(maxsize=1)
def country_currency() -> dict[str, str]:
    df = pd.read_csv(REFERENCE_DIR / "country_currency.csv", keep_default_na=False)
    return dict(zip(df["iso3"], df["currency"]))


# Codes in the dataset that are not ISO 4217 codes for the sending currency.
NONSTANDARD_CODES = {"CFA", "CLF"}


def standardize_send_currency(code: pd.Series, source_code: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Return (currency, was_fixed). 'CFA' becomes XOF/XAF by country; 'CLF' (a unit of account) becomes CLP."""
    mapping = country_currency()
    raw = code.fillna("").astype(str).str.strip().str.upper()
    country_ccy = source_code.map(mapping)
    fixed = raw.isin(NONSTANDARD_CODES) | (raw == "")
    return raw.where(~fixed, country_ccy), fixed


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["obs_id"] = df["sheet"] + ":" + df["rpw_id"].astype("Int64").astype(str)
    df["period"] = df["period"].astype(str).str.strip()
    df["period_date"] = period_to_date(df["period"]).dt.strftime("%Y-%m-%d")
    df["collected_date"] = parse_collected(df["collected_raw"]).dt.strftime("%Y-%m-%d")
    for col in ("source_code", "dest_code"):
        df[col] = df[col].astype(str).str.strip().str.upper()
    for col in ("source_region", "source_income", "dest_region", "dest_income"):
        df[col] = df[col].replace("..", np.nan)
    df["corridor"] = df["source_code"] + df["dest_code"]

    df["provider"], df["network"] = standardize_providers(df["firm_raw"])
    df["firm_type"] = df["firm_type"].map(standardize_firm_type)
    df["payment_instrument"] = df["payment_instrument"].map(tidy_text)
    df["access_point"] = df["access_point"].map(tidy_text)
    df["payout_method"] = df["pickup_raw"].map(standardize_payout)
    speed_key = df["speed_raw"].astype(str).str.strip().str.lower()
    df["speed_label"] = speed_key.map(SPEED_LABELS)
    df["speed_days_max"] = speed_key.map(SPEED_DAYS)

    df["send_currency"], df["send_currency_fixed"] = standardize_send_currency(df["cc1_code"], df["source_code"])
    df["receive_currency"] = df["dest_code"].map(country_currency())
    df["transparent"] = df["transparent_raw"].astype(str).str.strip().str.lower().map({"yes": 1, "no": 0})
    df["note"] = df["note"].map(tidy_text)
    return df
