"""Dagster definitions for FairSend's scheduled jobs (optional; `pip install -e ".[orchestration]"`).

    dagster dev -f orchestration/dagster_defs.py

Schedules:
  * daily 17:30 Europe/Berlin (after the ECB publishes ~16:00 CET): refresh FX rates, then run alert checks
  * weekly Monday 06:00: re-run the price pipeline; a no-op unless a new World Bank file is in data/raw/
"""

from dagster import Definitions, ScheduleDefinition, job, op

from fairsend import db
from fairsend.alerts import job as alert_job
from fairsend.pipeline import run as pipeline
from fairsend.pipeline.run import refresh_fx


@op
def refresh_rates(context) -> dict:
    with db.session() as conn:
        counts = refresh_fx(conn)
    context.log.info(f"FX refresh: {counts}")
    return counts


@op
def check_alerts(context, _rates: dict) -> dict:
    result = alert_job.run()
    context.log.info(f"Alerts: {result}")
    return result


@op
def load_prices(context) -> dict:
    summary = pipeline.run()
    context.log.info(f"Pipeline {summary['status']}: {summary.get('notes')}")
    failed = [r for r in summary.get("quality", []) if r["severity"] == "error" and r["pass_rate"] < 0.99]
    if failed:
        context.log.warning(f"Quality checks below 99% pass rate: {[r['check_name'] for r in failed]}")
    return {k: v for k, v in summary.items() if k != "quality"}


@job
def daily_rates_and_alerts():
    check_alerts(refresh_rates())


@job
def weekly_price_refresh():
    load_prices()


defs = Definitions(
    jobs=[daily_rates_and_alerts, weekly_price_refresh],
    schedules=[
        ScheduleDefinition(job=daily_rates_and_alerts, cron_schedule="30 17 * * 1-5", execution_timezone="Europe/Berlin"),
        ScheduleDefinition(job=weekly_price_refresh, cron_schedule="0 6 * * 1", execution_timezone="UTC"),
    ],
)
