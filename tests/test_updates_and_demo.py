"""Automatic World Bank updates, the compact demo database, and the keyword-search fallback for Ask."""

import datetime as dt
import gzip
import io
import sqlite3

import pytest

from fairsend import db, demo
from fairsend.explainer.index import KeywordIndex, chunk_corpus
from fairsend.pipeline import fetch

CATALOG = {"count": 2, "data": [
    {"name": "Remittance Prices Worldwide (Quarterly Report)", "last_updated_date": "2026-04-17T00:00:00+00:00",
     "distribution": {"url": "https://example.org/RPW_report.pdf", "file_name": "RPW_report.pdf",
                      "distribution_size": "3213221"}},
    {"name": "Remittance Prices Worldwide (Complete Dataset)", "last_updated_date": "2026-09-23T00:00:00+00:00",
     "maintenance_information": {"version_notes": "Q3 2025"},
     "distribution": {"url": "https://example.org/rpw_dataset_2011_2025_q3.xlsx",
                      "file_name": "rpw_dataset_2011_2025_q3.xlsx", "distribution_size": "12"}},
]}


def test_catalog_release_is_found():
    r = fetch.parse_release(CATALOG)
    assert r.file_name == "rpw_dataset_2011_2025_q3.xlsx"
    assert r.size == 12 and r.version == "Q3 2025" and r.last_updated == dt.date(2026, 9, 23)


def test_catalog_without_dataset_raises():
    with pytest.raises(fetch.ReleaseNotFound):
        fetch.parse_release({"data": [CATALOG["data"][0]]})


class FakeResponse:
    def __init__(self, body: bytes):
        self.raw = io.BytesIO(body)
        self._body = body

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_skips_identical_file_and_fetches_new_one(tmp_path, monkeypatch):
    r = fetch.parse_release(CATALOG)
    calls = []
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: calls.append(a) or FakeResponse(b"x" * 12))
    path, downloaded = fetch.download(r, tmp_path)
    assert downloaded and path.read_bytes() == b"x" * 12
    path, downloaded = fetch.download(r, tmp_path)       # same name and size: no second download
    assert not downloaded and len(calls) == 1


def test_incomplete_download_is_rejected(tmp_path, monkeypatch):
    r = fetch.parse_release(CATALOG)
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: FakeResponse(b"short"))
    with pytest.raises(IOError):
        fetch.download(r, tmp_path)
    assert not (tmp_path / r.file_name).exists()


def _tiny_full_db(path):
    conn = db.connect(path)
    conn.execute("INSERT INTO rpw_prices (obs_id, period, period_date, source_code, dest_code, corridor, provider, "
                 "send_currency, note, is_valid) VALUES ('v2:1','2025_3Q','2025-07-01','USA','IND','USAIND','Wise','USD',"
                 "'a long note', 1), ('v2:2','2025_3Q','2025-07-01','USA','IND','USAIND','Bad','USD','x', 0)")
    conn.execute("INSERT INTO fx_rates VALUES (date('now'),'USD','INR',95.0,'test','now'), "
                 "('2011-01-03','USD','INR',45.0,'test','now')")
    conn.commit()
    conn.close()


def test_demo_export_is_compact_and_marked(tmp_path):
    full = tmp_path / "full.db"
    _tiny_full_db(full)
    out = demo.export(tmp_path / "demo.db.gz", source=full)
    unpacked = tmp_path / "demo.db"
    unpacked.write_bytes(gzip.decompress(out.read_bytes()))
    with sqlite3.connect(unpacked) as conn:
        assert conn.execute("SELECT COUNT(*) FROM rpw_prices").fetchone()[0] == 1          # valid rows only
        assert conn.execute("SELECT note FROM rpw_prices").fetchone()[0] is None           # long text dropped
        assert conn.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0] == 1            # old rates dropped
    assert demo.is_demo(unpacked) and not demo.is_demo(full)


def test_ensure_database_downloads_only_when_needed(tmp_path, monkeypatch):
    full = tmp_path / "full.db"
    _tiny_full_db(full)
    gz = demo.export(tmp_path / "demo.db.gz", source=full).read_bytes()
    monkeypatch.setattr(demo.requests, "get", lambda *a, **k: FakeResponse(gz))
    target = tmp_path / "app.db"
    assert demo.ensure_database(target) == "downloaded" and demo.is_demo(target)
    assert demo.ensure_database(target) == "local"         # fresh demo copy is reused
    assert demo.ensure_database(full) == "local"           # a full local database is never replaced


def test_keyword_search_finds_sources_and_rejects_unrelated_questions():
    ix = KeywordIndex(chunk_corpus())
    top, score = ix.search("How long do I have to cancel a transfer?", 3)[0]
    assert "cancel" in (top.section + top.text).lower() and score >= ix.min_score
    assert all(s < ix.min_score for _, s in ix.search("What's the weather in Mumbai this week?", 3))
