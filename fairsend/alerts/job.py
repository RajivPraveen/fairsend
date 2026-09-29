"""Daily alert check: fire an alert when today's mid-market rate reaches the user's target.

An alert fires when (1) its condition is met by the latest published rate, (2) it has not already
fired for that same rate date, and (3) its cooldown since the last firing has passed. Each message
says where today's rate sits in its 90-day range (context, not a forecast) and links to the cheapest
provider on the route.

    fairsend alerts            # run once (schedule daily with cron, launchd, or Dagster)
"""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from typing import Callable
from urllib.parse import urlencode

from fairsend import compare, db, fx
from fairsend.alerts import notify, store
from fairsend.config import settings

log = logging.getLogger("fairsend.alerts")

RateFn = Callable[[str, str], fx.Rate]
HistoryFn = Callable[[str, str], "object"]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def should_fire(alert: store.Alert, rate: fx.Rate, last_fired_rate_date: str | None, now: dt.datetime) -> bool:
    if not alert.active or not alert.is_met(rate.rate):
        return False
    if last_fired_rate_date == rate.rate_date.isoformat():
        return False
    if alert.last_triggered_at:
        last = dt.datetime.fromisoformat(alert.last_triggered_at)
        if now - last < dt.timedelta(days=alert.cooldown_days):
            return False
    return True


def compare_link(alert: store.Alert, amount: float = 500) -> str:
    params = {"src": alert.source_code, "dst": alert.dest_code, "amount": int(amount)}
    return f"{settings.app_url.rstrip('/')}/compare?{urlencode(params)}"


def compose(alert: store.Alert, rate: fx.Rate, context: dict, best: str | None) -> tuple[str, str]:
    subject = f"FairSend: 1 {alert.send_currency} = {rate.rate:,.4g} {alert.receive_currency} (your target: {alert.target_rate:g})"
    lines = [f"Your rate alert was reached: {alert.description}.",
             f"Mid-market rate on {rate.rate_date}: 1 {alert.send_currency} = {rate.rate:,.4f} {alert.receive_currency} "
             f"({rate.source})."]
    if context:
        lines.append(f"Over the last {context['days']} published days the rate ranged from {context['low']:,.4f} to "
                     f"{context['high']:,.4f}; today is higher than {context['percentile']:.0f}% of those days. "
                     "This is context, not a prediction: exchange rates are hard to forecast.")
    if best:
        lines.append(best)
    if alert.source_code and alert.dest_code:
        lines.append(f"Compare providers now: {compare_link(alert)}")
    lines.append("Providers add their own markup to the mid-market rate, so the rate you get will be lower.")
    lines.append(f"Edit or delete this alert in FairSend with alert id {alert.alert_id} and your manage token.")
    return subject, "\n\n".join(lines)


def best_provider_line(conn: sqlite3.Connection, alert: store.Alert, rate: fx.Rate) -> str | None:
    if not (alert.source_code and alert.dest_code):
        return None
    try:
        c = compare.compare(alert.source_code, alert.dest_code, 500, conn=conn,
                            mid_rate=rate if rate.quote == alert.receive_currency else None)
    except (LookupError, fx.RateUnavailable):
        return None
    if c.best is None:
        return None
    b = c.best
    return (f"Cheapest option for {500:,} {c.send_currency} in the latest World Bank survey ({c.period}): "
            f"{b['provider']} ({b['payout_method']}), about {b['amount_received']:,.0f} {c.country_currency} delivered.")


def run(conn: sqlite3.Connection | None = None, *, rate_fn: RateFn | None = None,
        history_fn: HistoryFn | None = None, now: dt.datetime | None = None) -> dict:
    own = conn is None
    conn = conn or db.connect()
    now = now or _now()
    rate_fn = rate_fn or (lambda b, q: fx.get_rate(b, q, conn=conn))
    history_fn = history_fn or (lambda b, q: fx.get_history(b, q, (now - dt.timedelta(days=90)).date(), now.date(),
                                                            conn=conn))
    checked = fired = failed = 0
    rates: dict[tuple[str, str], fx.Rate] = {}
    try:
        for alert in store.active_alerts(conn):
            pair = (alert.send_currency, alert.receive_currency)
            try:
                rate = rates.get(pair) or rate_fn(*pair)
            except fx.RateUnavailable as exc:
                log.warning("No rate for %s: %s", pair, exc)
                continue
            rates[pair] = rate
            checked += 1
            conn.execute("UPDATE alerts SET last_checked_at=? WHERE alert_id=?",
                         (now.isoformat(timespec="seconds"), alert.alert_id))
            last = conn.execute("SELECT rate_date FROM alert_events WHERE alert_id=? AND status='sent' "
                                "ORDER BY event_id DESC LIMIT 1", (alert.alert_id,)).fetchone()
            if not should_fire(alert, rate, last["rate_date"] if last else None, now):
                continue
            try:
                context = fx.range_context(history_fn(*pair), rate.rate)
            except Exception:  # context is optional; never block an alert on it
                context = {}
            subject, body = compose(alert, rate, context, best_provider_line(conn, alert, rate))
            try:
                detail = notify.deliver(alert.channel, alert.contact, subject, body)
                status = "sent"
                fired += 1
                conn.execute("UPDATE alerts SET last_triggered_at=? WHERE alert_id=?",
                             (now.isoformat(timespec="seconds"), alert.alert_id))
            except notify.DeliveryError as exc:
                status, detail = "failed", str(exc)
                failed += 1
            conn.execute("INSERT INTO alert_events (alert_id, fired_at, rate, rate_date, channel, status, detail) "
                         "VALUES (?,?,?,?,?,?,?)",
                         (alert.alert_id, now.isoformat(timespec="seconds"), rate.rate, rate.rate_date.isoformat(),
                          alert.channel, status, detail))
        total = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM alerts WHERE active=1").fetchone()[0]
        conn.execute("INSERT OR REPLACE INTO alert_daily_stats (stat_date, active_alerts, total_created, fired_today) "
                     "VALUES (?,?,?,COALESCE((SELECT fired_today FROM alert_daily_stats WHERE stat_date=?),0)+?)",
                     (now.date().isoformat(), active, total, now.date().isoformat(), fired))
        conn.commit()
        return {"checked": checked, "fired": fired, "failed": failed}
    finally:
        if own:
            conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(run())


if __name__ == "__main__":
    main()
