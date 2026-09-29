"""Hand-calculated cost model cases (worked by hand; see comments)."""

import pytest

from fairsend import cost_model as cm


def test_principal_mode_small_transfer():
    # Send 200 USD, fee 5, provider rate 82.00 INR, mid 83.00.
    # markup = (83 - 82) / 83 = 1.204819%; markup cost = 200 * 1/83 = 2.409639; total = 7.409639 (3.704819%)
    c = cm.cost_from_principal(200, 5, 82.0, 83.0)
    assert c.markup_pct == pytest.approx(1.204819, abs=1e-6)
    assert c.markup_cost == pytest.approx(2.409639, abs=1e-6)
    assert c.total_cost == pytest.approx(7.409639, abs=1e-6)
    assert c.total_cost_pct == pytest.approx(3.704819, abs=1e-6)
    assert c.amount_received == pytest.approx(16400.0)
    assert c.total_paid == pytest.approx(205.0)
    assert c.fee_share_pct == pytest.approx(5 / 7.409639 * 100, abs=1e-4)


def test_budget_mode_fee_comes_out_of_amount():
    # Hand over 500 USD, fee 3.99 -> 496.01 converted at 85.5 (mid 86.4).
    # received = 42,408.855; markup = 0.9/86.4 = 1.0416667%; markup cost = 5.166771; total = 9.156771 (1.831354%)
    c = cm.cost_from_budget(500, 3.99, 85.5, 86.4)
    assert c.amount_converted == pytest.approx(496.01)
    assert c.amount_received == pytest.approx(42408.855)
    assert c.markup_cost == pytest.approx(5.166771, abs=1e-6)
    assert c.total_cost == pytest.approx(9.156771, abs=1e-6)
    assert c.total_cost_pct == pytest.approx(1.831354, abs=1e-6)
    # Budget-mode identity: total cost = budget - received / mid
    assert c.total_cost == pytest.approx(500 - c.amount_received / 86.4, abs=1e-9)


def test_zero_fee_transfer_still_costs_money():
    c = cm.cost_from_principal(1000, 0, 0.985 * 90, 90)
    assert c.fee == 0
    assert c.total_cost == pytest.approx(15.0)
    assert c.markup_share_pct == pytest.approx(100.0)


def test_large_tuition_example_from_spec():
    # "On a $20,000 tuition payment, a 3% markup costs $600."
    c = cm.cost_from_principal(20000, 0, 0.97 * 95.0, 95.0)
    assert c.markup_cost == pytest.approx(600.0)


def test_reproduces_world_bank_total_cost_formula():
    # Real RPW row (UAE -> Bangladesh, 2016 Q2): 735 AED, fee 15, rate 21.32, interbank 21.338, published total 2.13%
    c = cm.cost_from_principal(735, 15, 21.32, 21.338)
    assert c.total_cost_pct == pytest.approx(2.13, abs=0.01)


def test_cost_to_deliver_tuition():
    # Deliver 20,000 USD; mid 1 USD = 83 INR, quote 1 USD = 84.5 INR, fee 1,000 INR, 25 USD deducted in transit.
    # converted = 20,025 * 84.5 = 1,692,112.5 INR; paid = 1,693,112.5; fair = 1,660,000; cost = 33,112.5 INR = 398.946 USD
    c = cm.cost_to_deliver(20000, 1000, 1 / 84.5, 1 / 83, deducted_on_arrival=25)
    assert c.amount_converted == pytest.approx(1692112.5)
    assert c.total_paid == pytest.approx(1693112.5)
    assert c.fair_cost == pytest.approx(1660000)
    assert c.total_cost == pytest.approx(33112.5)
    assert c.total_cost_in_target == pytest.approx(398.946, abs=1e-3)
    assert c.markup_pct == pytest.approx((1 - 83 / 84.5) * 100)


def test_fee_larger_than_budget_is_rejected():
    with pytest.raises(ValueError):
        cm.cost_from_budget(5, 10, 80, 80)


def test_linear_fee_schedule():
    s = cm.LinearSchedule(200, 5, 500, 8)
    assert s.fixed_part == pytest.approx(3.0)
    assert s.percent_part == pytest.approx(1.0)
    assert s.at(350) == (pytest.approx(6.5), False)
    fee, extrapolated = s.at(20000)
    assert fee == pytest.approx(203.0) and extrapolated
    assert cm.LinearSchedule(200, 10, 500, 2).at(5000)[0] == 0.0  # floored at zero


def test_flat_fee_and_margin_hold():
    assert cm.LinearSchedule(200, 3.99, 500, 3.99).at(1000)[0] == pytest.approx(3.99)
    m = cm.LinearSchedule(200, 1.0, 500, 0.8, floor=None, hold_outside=True)
    assert m.at(350)[0] == pytest.approx(0.9)
    assert m.at(10000)[0] == pytest.approx(0.8)
    assert m.at(50)[0] == pytest.approx(1.0)


def test_single_point_schedule():
    fee, extrapolated = cm.LinearSchedule(200, 4.0).at(200)
    assert fee == 4.0 and not extrapolated


@pytest.mark.parametrize("quoted,mid,expected,inverted", [
    (83.12, 83.5, 83.12, False),          # 1 USD = 83.12 INR
    (0.012031, 83.5, 1 / 0.012031, True),  # 1 INR = 0.012031 USD
    (97.9, 1 / 96.0, 1 / 97.9, True),      # INR->USD payment quoted as 1 USD = 97.9 INR
])
def test_orient_rate(quoted, mid, expected, inverted):
    rate, was_inverted = cm.orient_rate(quoted, mid)
    assert rate == pytest.approx(expected)
    assert was_inverted is inverted
