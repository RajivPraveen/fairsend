"""Create, edit, and delete rate alerts.

Privacy: an alert stores only a contact (email or Telegram chat id), a currency pair, a target, and
an optional route for the "best provider" link. Deleting an alert removes the row and its delivery
history, so no contact details remain. Each alert has a secret manage token: whoever holds it can
edit or delete the alert, so no account or password is needed.
"""

from __future__ import annotations

import datetime as dt
import re
import secrets
import sqlite3
import uuid
from dataclasses import dataclass

CHANNELS = ("email", "telegram", "outbox")
DIRECTIONS = ("at_least", "at_most")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class Alert:
    alert_id: str
    manage_token: str
    created_at: str
    updated_at: str
    channel: str
    contact: str
    send_currency: str
    receive_currency: str
    source_code: str | None
    dest_code: str | None
    target_rate: float
    direction: str
    cooldown_days: int
    active: int
    last_checked_at: str | None
    last_triggered_at: str | None

    def is_met(self, rate: float) -> bool:
        return rate >= self.target_rate if self.direction == "at_least" else rate <= self.target_rate

    @property
    def description(self) -> str:
        word = "at least" if self.direction == "at_least" else "at most"
        return f"1 {self.send_currency} is worth {word} {self.target_rate:g} {self.receive_currency}"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def validate(channel: str, contact: str, send_currency: str, receive_currency: str, target_rate: float,
             direction: str) -> None:
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {CHANNELS}")
    if channel == "email" and not EMAIL_RE.match(contact):
        raise ValueError("Please enter a valid email address")
    if channel == "telegram" and not re.fullmatch(r"-?\d{3,20}", contact):
        raise ValueError("Telegram chat id should be a number (message the bot, then use /start to see it)")
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}")
    if not (target_rate > 0):
        raise ValueError("Target rate must be positive")
    if len(send_currency) != 3 or len(receive_currency) != 3 or send_currency == receive_currency:
        raise ValueError("Choose two different 3-letter currency codes")


def create(conn: sqlite3.Connection, *, channel: str, contact: str, send_currency: str, receive_currency: str,
           target_rate: float, direction: str = "at_least", source_code: str | None = None,
           dest_code: str | None = None, cooldown_days: int = 7) -> Alert:
    send_currency, receive_currency = send_currency.upper(), receive_currency.upper()
    contact = contact.strip()
    validate(channel, contact, send_currency, receive_currency, target_rate, direction)
    now = _now()
    alert = Alert(alert_id=uuid.uuid4().hex[:12], manage_token=secrets.token_urlsafe(16), created_at=now,
                  updated_at=now, channel=channel, contact=contact, send_currency=send_currency,
                  receive_currency=receive_currency, source_code=source_code, dest_code=dest_code,
                  target_rate=float(target_rate), direction=direction, cooldown_days=int(cooldown_days),
                  active=1, last_checked_at=None, last_triggered_at=None)
    cols = list(alert.__dict__)
    conn.execute(f"INSERT INTO alerts ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                 tuple(alert.__dict__.values()))
    conn.commit()
    return alert


def _row(row: sqlite3.Row | None) -> Alert | None:
    return Alert(**dict(row)) if row else None


def get(conn: sqlite3.Connection, alert_id: str, manage_token: str) -> Alert | None:
    row = conn.execute("SELECT * FROM alerts WHERE alert_id=? AND manage_token=?",
                       (alert_id, manage_token)).fetchone()
    return _row(row)


def list_for_contact(conn: sqlite3.Connection, contact: str, manage_token: str) -> list[Alert]:
    """Alerts owned by a contact; the token of any one of them proves ownership."""
    owner = conn.execute("SELECT 1 FROM alerts WHERE contact=? AND manage_token=?",
                         (contact.strip(), manage_token)).fetchone()
    if not owner:
        return []
    rows = conn.execute("SELECT * FROM alerts WHERE contact=? ORDER BY created_at", (contact.strip(),)).fetchall()
    return [_row(r) for r in rows]


def active_alerts(conn: sqlite3.Connection) -> list[Alert]:
    return [_row(r) for r in conn.execute("SELECT * FROM alerts WHERE active=1").fetchall()]


EDITABLE = {"target_rate", "direction", "active", "cooldown_days", "channel", "contact"}


def update(conn: sqlite3.Connection, alert_id: str, manage_token: str, **changes) -> Alert:
    alert = get(conn, alert_id, manage_token)
    if alert is None:
        raise PermissionError("Alert not found or wrong manage token")
    bad = set(changes) - EDITABLE
    if bad:
        raise ValueError(f"Cannot edit {bad}")
    merged = {**alert.__dict__, **changes}
    validate(merged["channel"], merged["contact"], merged["send_currency"], merged["receive_currency"],
             float(merged["target_rate"]), merged["direction"])
    changes["updated_at"] = _now()
    sets = ", ".join(f"{k}=?" for k in changes)
    conn.execute(f"UPDATE alerts SET {sets} WHERE alert_id=?", (*changes.values(), alert_id))
    conn.commit()
    return get(conn, alert_id, manage_token)


def delete(conn: sqlite3.Connection, alert_id: str, manage_token: str) -> bool:
    if get(conn, alert_id, manage_token) is None:
        return False
    conn.execute("DELETE FROM alert_events WHERE alert_id=?", (alert_id,))
    conn.execute("DELETE FROM alerts WHERE alert_id=?", (alert_id,))
    conn.commit()
    return True
