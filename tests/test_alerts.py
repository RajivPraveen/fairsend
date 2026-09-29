"""Alert reliability: alerts fire when the target is reached and never when it isn't."""

import datetime as dt

import pytest

from fairsend import db, fx
from fairsend.alerts import job, notify, store

UTC = dt.timezone.utc


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(notify, "OUTBOX_DIR", tmp_path / "outbox")
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def make(conn, **kw):
    args = dict(channel="outbox", contact="me@example.com", send_currency="USD", receive_currency="INR",
                target_rate=88.0, direction="at_least", cooldown_days=7)
    args.update(kw)
    return store.create(conn, **args)


def day(n):
    return dt.datetime(2026, 1, 1, 18, tzinfo=UTC) + dt.timedelta(days=n)


def run_at(conn, rate, n, quote="INR"):
    r = fx.Rate("USD", quote, rate, day(n).date(), "test")
    return job.run(conn, rate_fn=lambda b, q: fx.Rate(b, q, r.rate, r.rate_date, "test"),
                   history_fn=lambda b, q: __import__("pandas").DataFrame(columns=["date", "rate"]), now=day(n))


def events(conn):
    return conn.execute("SELECT status FROM alert_events").fetchall()


def test_does_not_fire_below_target(conn):
    make(conn)
    assert run_at(conn, 87.99, 0)["fired"] == 0
    assert events(conn) == []


def test_fires_exactly_at_target(conn):
    make(conn)
    assert run_at(conn, 88.0, 0)["fired"] == 1
    assert len(list((notify.OUTBOX_DIR).glob("*.txt"))) == 1


def test_cooldown_blocks_repeat_then_allows(conn):
    make(conn, cooldown_days=7)
    assert run_at(conn, 88.5, 0)["fired"] == 1
    assert run_at(conn, 88.7, 1)["fired"] == 0     # within cooldown
    assert run_at(conn, 88.7, 6)["fired"] == 0
    assert run_at(conn, 88.9, 7)["fired"] == 1     # cooldown elapsed


def test_same_rate_date_never_fires_twice(conn):
    a = make(conn, cooldown_days=1)
    assert run_at(conn, 89, 0)["fired"] == 1
    # The job runs again later with the same published rate (e.g. weekend, no new ECB fixing).
    later = day(3)
    r = fx.Rate("USD", "INR", 89, day(0).date(), "test")
    assert job.run(conn, rate_fn=lambda b, q: r, history_fn=lambda b, q: __import__("pandas").DataFrame(),
                   now=later)["fired"] == 0
    assert store.get(conn, a.alert_id, a.manage_token).last_triggered_at.startswith("2026-01-01")


def test_at_most_direction(conn):
    make(conn, direction="at_most", target_rate=80.0)
    assert run_at(conn, 80.01, 0)["fired"] == 0
    assert run_at(conn, 79.99, 1)["fired"] == 1


def test_paused_and_deleted_alerts_never_fire(conn):
    a = make(conn)
    store.update(conn, a.alert_id, a.manage_token, active=0)
    assert run_at(conn, 99, 0)["fired"] == 0
    store.update(conn, a.alert_id, a.manage_token, active=1)
    assert store.delete(conn, a.alert_id, a.manage_token)
    assert run_at(conn, 99, 1)["fired"] == 0
    assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM alert_events").fetchone()[0] == 0


def test_failed_delivery_is_retried_next_day(conn, monkeypatch):
    make(conn)
    real_deliver = notify.deliver

    def boom(*a, **k):
        raise notify.DeliveryError("smtp down")
    monkeypatch.setattr(notify, "deliver", boom)
    assert run_at(conn, 90, 0) == {"checked": 1, "fired": 0, "failed": 1}
    monkeypatch.setattr(notify, "deliver", real_deliver)
    assert run_at(conn, 90, 1)["fired"] == 1
    assert [e[0] for e in events(conn)] == ["failed", "sent"]


def test_manage_token_required(conn):
    a = make(conn)
    with pytest.raises(PermissionError):
        store.update(conn, a.alert_id, "wrong-token", target_rate=90)
    assert not store.delete(conn, a.alert_id, "wrong-token")
    assert store.list_for_contact(conn, "me@example.com", "wrong-token") == []
    assert len(store.list_for_contact(conn, "me@example.com", a.manage_token)) == 1


@pytest.mark.parametrize("kw", [dict(channel="email", contact="not-an-email"), dict(target_rate=0),
                                dict(send_currency="USD", receive_currency="USD"), dict(direction="sideways"),
                                dict(channel="telegram", contact="@handle")])
def test_invalid_alerts_rejected(conn, kw):
    with pytest.raises(ValueError):
        make(conn, **kw)


def test_scenario_matrix_never_fires_when_condition_false(conn):
    """Randomized scenarios: over 200 days, every firing coincides with the condition being met."""
    import random
    rng = random.Random(3)
    make(conn, cooldown_days=3, target_rate=85.0)
    fired_days = []
    for n in range(200):
        rate = 85 + rng.uniform(-2, 2)
        if run_at(conn, rate, n)["fired"]:
            fired_days.append((n, rate))
    assert fired_days, "expected some firings"
    assert all(rate >= 85.0 for _, rate in fired_days)
    assert all(b[0] - a_[0] >= 3 for a_, b in zip(fired_days, fired_days[1:]))


def test_message_contains_context_and_disclaimer():
    a = store.Alert("abc", "tok", "", "", "outbox", "x@y.z", "USD", "INR", "USA", "IND", 88, "at_least", 7, 1, None, None)
    r = fx.Rate("USD", "INR", 88.4, dt.date(2026, 1, 2), "ECB via Frankfurter")
    subject, body = job.compose(a, r, {"days": 60, "low": 86.0, "high": 89.0, "percentile": 80.0}, None)
    assert "88.4" in subject
    assert "not a prediction" in body
    assert "compare?src=USA&dst=IND" in body
