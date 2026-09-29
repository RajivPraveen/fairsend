"""A compact copy of the database for the hosted demo, and the code that fetches it at startup.

The full database (~190 MB) is rebuilt from the World Bank file by the pipeline. The demo copy keeps every valid
price since 2011 but drops long text notes, quality flags and old exchange-rate history, which brings it to
~17 MB compressed. A scheduled GitHub Action rebuilds it weekly and publishes it as a release file; a hosted app
with no local database downloads it on startup.
"""

from __future__ import annotations

import datetime as dt
import gzip
import logging
import os
import shutil
import sqlite3
from pathlib import Path

import requests

from fairsend import db
from fairsend.config import settings

log = logging.getLogger("fairsend.demo")

DEMO_DB_URL = os.getenv("FAIRSEND_DEMO_DB_URL",
                        "https://github.com/RajivPraveen/fairsend/releases/download/data/fairsend_demo.db.gz")
DROP_COLUMNS = {"note", "quality_flags", "first_seen_run", "last_seen_run", "firm_raw"}
FX_DAYS = 130            # enough for the 90-day chart on the alerts page
MAX_AGE_DAYS = 7         # a downloaded demo copy is refreshed after this long


def export(out_gz: Path, source: Path | None = None) -> Path:
    """Write a compressed demo database built from the full one."""
    source = Path(source or settings.db_path)
    out_gz.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_gz.with_suffix("")  # .db next to the .gz
    tmp.unlink(missing_ok=True)
    conn = db.connect(tmp)
    try:
        conn.execute("ATTACH DATABASE ? AS src", (str(source),))
        cols = [r[1] for r in conn.execute("PRAGMA src.table_info(rpw_prices)") if r[1] not in DROP_COLUMNS]
        conn.execute(f"INSERT INTO rpw_prices ({','.join(cols)}) SELECT {','.join(cols)} "
                     "FROM src.rpw_prices WHERE is_valid = 1")
        conn.execute("INSERT INTO fx_rates SELECT * FROM src.fx_rates WHERE rate_date >= date('now', ?)",
                     (f"-{FX_DAYS} days",))
        conn.execute("INSERT INTO pipeline_runs SELECT * FROM src.pipeline_runs WHERE status = 'success' "
                     "ORDER BY finished_at DESC LIMIT 1")
        conn.execute("INSERT INTO quality_results SELECT * FROM src.quality_results WHERE run_id = "
                     "(SELECT run_id FROM pipeline_runs LIMIT 1)")
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                         [("build", "demo"), ("built_at", dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))])
        conn.commit()
        conn.execute("DETACH DATABASE src")
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("VACUUM")
    finally:
        conn.close()
    with open(tmp, "rb") as f, gzip.open(out_gz, "wb", compresslevel=9) as g:
        shutil.copyfileobj(f, g)
    tmp.unlink()
    return out_gz


def is_demo(db_path: Path | None = None) -> bool:
    """True when running on the compact demo database (e.g. the hosted demo)."""
    path = Path(db_path or settings.db_path)
    if not path.exists():
        return False
    try:
        with sqlite3.connect(path) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'build'").fetchone()
        return bool(row and row[0] == "demo")
    except sqlite3.Error:
        return False


def ensure_database(db_path: Path | None = None, url: str = DEMO_DB_URL) -> str:
    """Make sure a database exists. Returns "local", "downloaded", or "missing".

    A full local database (built by the pipeline) is always used as is. Otherwise the published demo copy is
    downloaded, and re-downloaded once it is more than MAX_AGE_DAYS old so a hosted demo stays current.
    """
    path = Path(db_path or settings.db_path)
    if path.exists() and not is_demo(path):
        return "local"
    if path.exists():
        age = dt.datetime.now().timestamp() - path.stat().st_mtime
        if age < MAX_AGE_DAYS * 86400:
            return "local"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".download")
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with gzip.GzipFile(fileobj=r.raw) as src, open(part, "wb") as dst:
                shutil.copyfileobj(src, dst)
        part.replace(path)
        log.info("Downloaded demo database to %s", path)
        return "downloaded"
    except (requests.RequestException, OSError) as exc:
        log.warning("Could not download the demo database: %s", exc)
        return "local" if path.exists() else "missing"
