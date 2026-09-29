"""Deliver alert messages by email (SMTP), Telegram, or a local outbox folder for testing."""

from __future__ import annotations

import datetime as dt
import smtplib
from email.message import EmailMessage

import requests

from fairsend.config import OUTBOX_DIR, settings


class DeliveryError(RuntimeError):
    pass


def channel_configured(channel: str) -> bool:
    if channel == "email":
        return bool(settings.smtp_host and settings.smtp_from)
    if channel == "telegram":
        return bool(settings.telegram_bot_token)
    return channel == "outbox"


def send_email(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise DeliveryError(f"email failed: {exc}") from exc


def send_telegram(chat_id: str, subject: str, body: str) -> None:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": f"{subject}\n\n{body}",
                                     "disable_web_page_preview": True}, timeout=20)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise DeliveryError(f"telegram failed: {exc}") from exc


def send_outbox(contact: str, subject: str, body: str) -> None:
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    (OUTBOX_DIR / f"{stamp}.txt").write_text(f"To: {contact}\nSubject: {subject}\n\n{body}\n")


def deliver(channel: str, contact: str, subject: str, body: str) -> str:
    """Send through the alert's channel; falls back to the outbox if that channel is not configured."""
    if channel != "outbox" and not channel_configured(channel):
        send_outbox(contact, subject, body)
        return f"{channel} not configured; written to outbox"
    {"email": send_email, "telegram": send_telegram, "outbox": send_outbox}[channel](contact, subject, body)
    return "sent"
