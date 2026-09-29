"""Comparison, tuition, savings, explainer guardrails, and global analysis on the real database.

These tests use data/fairsend.db built by the pipeline and are skipped if it doesn't exist yet.
A fixed mid-market rate is passed in so no network access is needed.
"""

import datetime as dt

import pytest

from fairsend import compare, db, fx, savings, tuition
from fairsend.config import settings
from fairsend.explainer import answer

needs_db = pytest.mark.skipif(not settings.db_path.exists(), reason="run the pipeline first")
MID = fx.Rate("USD", "INR", 95.0, dt.date(2026, 9, 28), "test")


@needs_db
def test_compare_ranks_by_amount_received():
    c = compare.compare("USA", "IND", 500, mid_rate=MID)
    t = c.table
    assert len(t) > 10
    assert t["amount_received"].is_monotonic_decreasing
    assert (t.loc[~t["promotional_rate"], "amount_received"] <= 500 * 95.0 + 1e-6).all()
    assert (t["transparent"] == 1).all()
    # promotions keep their surveyed (negative) markup and are flagged
    assert (t.loc[t["total_cost"] < 0, "promotional_rate"]).all()
    # budget identity holds for every row
    assert ((500 - t["amount_received"] / 95.0) - t["total_cost"]).abs().max() < 1e-6


@needs_db
def test_compare_filters():
    c = compare.compare("USA", "IND", 500, payout_methods=["Bank account"], max_days=0.5, mid_rate=MID)
    assert c.table["payout_method"].str.contains("Bank account").all()
    assert (c.table["speed_days_max"] <= 0.5).all()


@needs_db
def test_savings_summary():
    s = savings.summarize("USA", "IND", 300, 12, None, comparison=compare.compare("USA", "IND", 300, mid_rate=MID))
    assert s.yearly_savings >= 0
    assert s.yearly_cost_best <= s.yearly_cost_current
    assert "a year" in s.message or "cheapest" in s.message


@needs_db
def test_tuition_benchmarks_and_deadline():
    opts = tuition.benchmark_options("INR", usd_to_pay=95.0)
    assert {o.name for o in opts} == {"Typical bank transfer", "Typical online money transfer service"}
    mid = fx.Rate("INR", "USD", 1 / 95.0, dt.date(2026, 9, 28), "test")
    today = dt.date(2026, 9, 28)  # a Monday
    r = tuition.evaluate(20000, "USD", "INR", today + dt.timedelta(days=2), opts, mid_rate=mid, today=today)
    assert r.business_days_left == 2
    assert set(r.table["deadline_status"]) <= {"On time", "Tight", "Too late"}
    assert (r.table["total_paid"] > 20000 * 95.0).all()


def test_business_days():
    assert tuition.business_days_until(dt.date(2026, 10, 5), dt.date(2026, 10, 2)) == 1  # Fri -> Mon
    assert tuition.deadline_status(2, 5, 2) == "On time"
    assert tuition.deadline_status(4, 5, 2) == "Tight"
    assert tuition.deadline_status(6, 5, 2) == "Too late"


@pytest.mark.parametrize("q,advice", [
    ("Should I wait until next month to send money?", True),
    ("Will the rupee fall next week?", True),
    ("Should I invest my savings instead of sending them home?", True),
    ("What is the best time to convert dollars?", True),
    # paraphrases that are not in the explainer eval set
    ("Is today a good day to change my pounds to naira?", True),
    ("Is this week the right moment to exchange money?", True),
    ("Should I hold off until the peso gets stronger?", True),
    ("Should I convert my savings to dollars now?", True),
    ("Is it a bad month to send money home?", True),
    ("What is a good way to check the exchange rate?", False),
    ("How long does a bank wire take?", False),
    ("Why is a zero-fee transfer not really free?", False),
    ("How long do I have to cancel a transfer?", False),
    ("What does my provider have to tell me before I send money?", False),
])
def test_advice_guard(q, advice):
    assert answer.is_advice_request(q) is advice


@needs_db
def test_global_headlines():
    from fairsend.analysis import global_costs as g
    with db.session() as conn:
        df = g.load(conn)
    h = g.headline_numbers(df)
    assert h["corridors"] > 300 and h["periods"] > 40
    assert 0 < h["corridors_below_3_pct"] < 100
    assert 0 < h["markup_share_pct"] < 100


@needs_db
def test_tuition_uses_real_providers_for_the_currency_pair():
    opts, scope = tuition.real_options("INR", "USD")
    assert scope == "pair"
    assert all(o.kind == "provider" and o.basis.startswith("World Bank survey") for o in opts)
    assert "State Bank of India" in {o.name for o in opts}
    assert all(o.deducted_on_arrival == 0 for o in opts)   # no assumed wire deductions


@needs_db
def test_tuition_falls_back_to_worldwide_medians_when_pair_not_surveyed():
    opts, scope = tuition.real_options("CNY", "USD")
    assert scope == "worldwide" and len(opts) == 2
