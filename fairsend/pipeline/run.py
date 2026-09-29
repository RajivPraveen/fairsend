"""Pipeline entry point: ingest -> clean -> join ECB rates -> quality checks -> load -> refresh FX.

Run with `fairsend pipeline` (or `python -m fairsend.pipeline.run`). Re-running on the same source
file is a no-op for price data (detected by file hash) unless --force is given; FX rates are always
refreshed. Rows are upserted by a stable id, so history accumulates across World Bank releases.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sqlite3
import uuid
from pathlib import Path

import pandas as pd
import requests

from fairsend import db, fx
from fairsend.config import latest_rpw_file
from fairsend.pipeline import clean, currency, ingest, quality

log = logging.getLogger("fairsend.pipeline")

PRICE_COLUMNS = [
    "obs_id", "rpw_id", "period", "period_date", "collected_date",
    "source_code", "source_name", "source_region", "source_income",
    "dest_code", "dest_name", "dest_region", "dest_income", "corridor",
    "firm_raw", "provider", "network", "firm_type", "payment_instrument", "access_point",
    "payout_method", "speed_label", "speed_days_max", "send_currency", "receive_currency",
    "country_currency", "payout_currency_basis", "ecb_mid_rate",
    "amt200_lcu", "fee200_lcu", "fx_rate200", "margin200_pct", "total200_pct",
    "amt500_lcu", "fee500_lcu", "fx_rate500", "margin500_pct", "total500_pct",
    "interbank_fx", "transparent", "note", "quality_flags", "is_valid",
]


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def join_ecb_rates(conn: sqlite3.Connection, df: pd.DataFrame, fetch: bool = True) -> pd.DataFrame:
    """Load ECB history, infer each product's payout currency, and attach the ECB rate on the collection date."""
    dates = pd.to_datetime(df["collected_date"], errors="coerce")
    if fetch and dates.notna().any():
        start = (dates.min() - pd.Timedelta(days=7)).date().isoformat()
        end = dates.max().date().isoformat()
        try:
            n = fx.backfill_ecb_pairs(conn, currency.candidate_pairs(df), start, end)
            log.info("Backfilled %s ECB daily rates", n)
        except requests.RequestException as exc:
            log.warning("ECB backfill failed (%s); using cached rates only", exc)
    ecb = currency.ecb_table(conn)
    df = currency.infer_receive_currency(df, ecb)
    keys = pd.DataFrame({"base": df["send_currency"], "quote": df["receive_currency"], "_date": dates})
    df["ecb_mid_rate"] = currency._rate_lookup(ecb, keys)
    return df


def upsert_prices(conn: sqlite3.Connection, df: pd.DataFrame, run_id: str) -> None:
    out = df[PRICE_COLUMNS].copy()
    out = out.astype(object).where(out.notna(), None)
    cols = PRICE_COLUMNS + ["first_seen_run", "last_seen_run"]
    placeholders = ",".join("?" * len(cols))
    updates = ",".join(f"{c}=excluded.{c}" for c in PRICE_COLUMNS[1:] + ["last_seen_run"])
    sql = (f"INSERT INTO rpw_prices ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT(obs_id) DO UPDATE SET {updates}")
    rows = [tuple(r) + (run_id, run_id) for r in out.itertuples(index=False, name=None)]
    conn.executemany(sql, rows)


def refresh_fx(conn: sqlite3.Connection) -> dict[str, int]:
    pairs = {tuple(r) for r in conn.execute(
        "SELECT DISTINCT send_currency, receive_currency FROM rpw_prices "
        "WHERE is_valid=1 AND period_date=(SELECT MAX(period_date) FROM rpw_prices)"
    ).fetchall()}
    pairs |= {tuple(r) for r in conn.execute(
        "SELECT DISTINCT send_currency, receive_currency FROM alerts WHERE active=1").fetchall()}
    counts = fx.refresh_latest(conn, pairs)
    conn.commit()
    return counts


def run(source: Path | None = None, db_path: Path | str | None = None, force: bool = False,
        fetch_fx: bool = True) -> dict:
    source = source or latest_rpw_file()
    run_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    conn = db.connect(db_path)
    conn.execute("INSERT INTO pipeline_runs (run_id, started_at, source_file) VALUES (?,?,?)",
                 (run_id, _now(), str(source) if source else None))
    conn.commit()
    summary: dict = {"run_id": run_id}
    try:
        if source is None or not Path(source).exists():
            raise FileNotFoundError(
                "No World Bank RPW workbook found. Download rpw_dataset_*.xlsx from "
                "https://datacatalog.worldbank.org/search/dataset/0037898 into data/raw/")
        sha = ingest.file_sha256(Path(source))
        prev = conn.execute("SELECT run_id FROM pipeline_runs WHERE source_sha256=? AND status='success'",
                            (sha,)).fetchone()
        if prev and not force:
            status, notes = "skipped", f"Source unchanged since run {prev['run_id']}"
            summary.update(status=status, notes=notes)
        else:
            log.info("Reading %s", source)
            raw = ingest.read_rpw_workbook(Path(source))
            cleaned = clean.clean(raw)
            joined = join_ecb_rates(conn, cleaned, fetch=fetch_fx)
            checked, results = quality.run_checks(joined)
            upsert_prices(conn, checked, run_id)
            conn.executemany(
                "INSERT OR REPLACE INTO quality_results (run_id, check_name, severity, rows_checked, rows_failed, "
                "pass_rate, description) VALUES (?,?,?,?,?,?,?)",
                [(run_id, r["check_name"], r["severity"], r["rows_checked"], r["rows_failed"], r["pass_rate"],
                  r["description"]) for r in results])
            n_valid = int(checked["is_valid"].sum())
            status = "success"
            notes = f"{checked['period'].nunique()} periods, {checked['corridor'].nunique()} corridors"
            conn.execute("UPDATE pipeline_runs SET source_sha256=?, rows_in=?, rows_valid=?, rows_flagged=? "
                         "WHERE run_id=?",
                         (sha, len(checked), n_valid, int((checked["quality_flags"] != "").sum()), run_id))
            summary.update(status=status, rows_in=len(checked), rows_valid=n_valid, notes=notes,
                           quality=results)
        if fetch_fx:
            summary["fx_refresh"] = refresh_fx(conn)
        conn.execute("UPDATE pipeline_runs SET status=?, finished_at=?, notes=? WHERE run_id=?",
                     (status, _now(), notes, run_id))
        conn.commit()
        return summary
    except Exception as exc:
        conn.rollback()
        conn.execute("UPDATE pipeline_runs SET status='failed', finished_at=?, notes=? WHERE run_id=?",
                     (_now(), f"{type(exc).__name__}: {exc}", run_id))
        conn.commit()
        raise
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the FairSend data pipeline")
    parser.add_argument("--source", type=Path, help="RPW workbook (default: newest data/raw/rpw_dataset_*.xlsx)")
    parser.add_argument("--force", action="store_true", help="Reload even if the source file is unchanged")
    parser.add_argument("--offline", action="store_true", help="Skip all exchange-rate API calls")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    summary = run(args.source, force=args.force, fetch_fx=not args.offline)
    print(f"Run {summary['run_id']}: {summary['status']} - {summary.get('notes', '')}")
    if "rows_in" in summary:
        print(f"  rows: {summary['rows_in']:,} loaded, {summary['rows_valid']:,} valid")
        for r in summary["quality"]:
            print(f"  [{r['severity']:7}] {r['check_name']:28} pass {r['pass_rate']:.2%}  ({r['rows_failed']:,} rows)")
    if "fx_refresh" in summary:
        print(f"  fx refresh: {summary['fx_refresh']}")


if __name__ == "__main__":
    main()
