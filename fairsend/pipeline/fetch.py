"""Find and download the newest World Bank Remittance Prices Worldwide file.

The World Bank publishes the complete dataset as one Excel file, replaced every quarter. Its public data catalog
API lists the current file's name, size, and update date, so FairSend can tell when a new quarter is out and
download only then.

    fairsend update        # download a new quarter if there is one, then rebuild the database
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path

import requests

from fairsend.config import RAW_DIR

log = logging.getLogger("fairsend.fetch")

CATALOG_API = "https://ddh-openapi.worldbank.org/resources"
DATASET_ID = "0037898"   # Remittance Prices Worldwide in the World Bank data catalog
TIMEOUT = 60


class ReleaseNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    file_name: str          # e.g. rpw_dataset_2011_2025_q3.xlsx
    url: str
    size: int | None        # bytes, as reported by the catalog
    last_updated: dt.date | None
    version: str | None     # e.g. "Q3 2025"


def parse_release(payload: dict) -> Release:
    """Pick the complete-dataset Excel file out of the catalog's resource list."""
    for resource in payload.get("data", []):
        dist = resource.get("distribution") or {}
        name = dist.get("file_name") or (dist.get("url") or "").rsplit("/", 1)[-1]
        if dist.get("url") and name.startswith("rpw_dataset") and name.endswith(".xlsx"):
            updated = resource.get("last_updated_date")
            size = dist.get("distribution_size")
            return Release(
                file_name=name, url=dist["url"],
                size=int(size) if size and str(size).isdigit() else None,
                last_updated=dt.date.fromisoformat(updated[:10]) if updated else None,
                version=(resource.get("maintenance_information") or {}).get("version_notes"),
            )
    raise ReleaseNotFound("The catalog lists no rpw_dataset_*.xlsx file")


def latest_release() -> Release:
    r = requests.get(CATALOG_API, params={"dataset_unique_id": DATASET_ID}, timeout=TIMEOUT)
    r.raise_for_status()
    return parse_release(r.json())


def download(release: Release, raw_dir: Path = RAW_DIR) -> tuple[Path, bool]:
    """Download the release unless an identical file is already there. Returns (path, downloaded)."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / release.file_name
    if target.exists() and (release.size is None or target.stat().st_size == release.size):
        log.info("Already have %s", target.name)
        return target, False
    part = target.with_suffix(target.suffix + ".part")
    log.info("Downloading %s (%s)", release.url, f"{release.size / 1e6:.1f} MB" if release.size else "size unknown")
    with requests.get(release.url, stream=True, timeout=TIMEOUT, headers={"User-Agent": "FairSend data pipeline"}) as r:
        r.raise_for_status()
        with open(part, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    if release.size is not None and part.stat().st_size != release.size:
        part.unlink()
        raise IOError(f"Download incomplete: expected {release.size} bytes")
    part.replace(target)
    return target, True
