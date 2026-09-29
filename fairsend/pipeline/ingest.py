"""Load the World Bank Remittance Prices Worldwide workbook into one DataFrame with a single schema.

The workbook has two data sheets whose layouts differ (the survey changed in Q2 2016):
  * "Dataset (up to Q1 2016)": product, sending location, coverage, pick-up method, note1
  * "Dataset (from Q2 2016)":  payment instrument, access point, receiving network coverage,
                               pickup method, Standard Note
Both are mapped onto the same column names here; nothing is cleaned yet.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

OLD_SHEET = "Dataset (up to Q1 2016)"
NEW_SHEET = "Dataset (from Q2 2016)"

COMMON = {
    "id": "rpw_id", "period": "period",
    "source_code": "source_code", "source_name": "source_name",
    "source_region": "source_region", "source_income": "source_income",
    "destination_code": "dest_code", "destination_name": "dest_name",
    "destination_region": "dest_region", "destination_income": "dest_income",
    "firm": "firm_raw", "firm_type": "firm_type", "speed actual": "speed_raw",
    "cc1 lcu amount": "amt200_lcu", "cc1 denomination amount": "denom200", "cc1 lcu code": "cc1_code",
    "cc1 lcu fee": "fee200_lcu", "cc1 lcu fx rate": "fx_rate200", "cc1 fx margin": "margin200_pct",
    "cc1 total cost %": "total200_pct",
    "cc2 lcu amount": "amt500_lcu", "cc2 denomination amount": "denom500", "cc2 lcu code": "cc2_code",
    "cc2 lcu fee": "fee500_lcu", "cc2 lcu fx rate": "fx_rate500", "cc2 fx margin": "margin500_pct",
    "cc2 total cost %": "total500_pct",
    "inter lcu bank fx": "interbank_fx", "transparent": "transparent_raw",
    "date": "collected_raw", "corridor": "corridor",
}
OLD_ONLY = {"product": "payment_instrument", "sending location": "access_point",
            "pick-up method": "pickup_raw", "note1": "note"}
NEW_ONLY = {"payment instrument": "payment_instrument", "access point": "access_point",
            "pickup method": "pickup_raw", "Standard Note": "note"}

NUMERIC = ["amt200_lcu", "denom200", "fee200_lcu", "fx_rate200", "margin200_pct", "total200_pct",
           "amt500_lcu", "denom500", "fee500_lcu", "fx_rate500", "margin500_pct", "total500_pct",
           "interbank_fx"]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_sheet(df: pd.DataFrame, extra: dict[str, str], sheet_key: str) -> pd.DataFrame:
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
    mapping = {**COMMON, **extra}
    missing = [c for c in mapping if c not in df.columns]
    if missing:
        raise ValueError(f"Sheet {sheet_key!r} is missing expected columns: {missing}")
    out = df[list(mapping)].rename(columns=mapping)
    out.insert(0, "sheet", sheet_key)
    for col in NUMERIC:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def read_rpw_workbook(path: Path) -> pd.DataFrame:
    sheets = pd.read_excel(path, sheet_name=[OLD_SHEET, NEW_SHEET])
    old = _normalize_sheet(sheets[OLD_SHEET], OLD_ONLY, "v1")
    new = _normalize_sheet(sheets[NEW_SHEET], NEW_ONLY, "v2")
    return pd.concat([old, new], ignore_index=True)
