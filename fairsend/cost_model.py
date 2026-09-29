"""True total cost of a transfer: upfront fee plus the hidden exchange-rate markup.

Definitions (all amounts in the sending currency unless noted):
    markup %       = (mid_rate - provider_rate) / mid_rate * 100
    markup cost    = amount converted * markup % / 100
    total cost     = fee + markup cost
    amount received (receiving currency) = amount converted * provider_rate

Two ways to describe a transfer:
    budget mode    - the sender hands over a fixed amount and the fee comes out of it
                     (amount converted = budget - fee). Used for comparisons, because it makes
                     "how much arrives" directly comparable across providers.
    principal mode - the sender converts a fixed amount and pays the fee on top
                     (amount converted = principal). This is the World Bank's convention, where
                     total cost % = fee / principal + FX margin.
In both, total cost % is expressed relative to the amount the user entered.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CostBreakdown:
    mode: str                 # "budget" | "principal"
    entered_amount: float     # what the user entered (budget or principal)
    amount_converted: float   # principal that is exchanged
    fee: float
    total_paid: float         # money leaving the sender: amount_converted + fee
    provider_rate: float      # receive units per send unit
    mid_rate: float
    amount_received: float    # receiving currency
    received_at_mid: float    # receiving currency: total_paid converted at mid with no fee
    markup_pct: float
    markup_cost: float
    total_cost: float
    total_cost_pct: float     # % of entered_amount
    fee_share_pct: float      # share of total cost that is the visible fee
    markup_share_pct: float   # share of total cost hidden in the exchange rate

    def as_dict(self) -> dict:
        return asdict(self)


def markup_pct(provider_rate: float, mid_rate: float) -> float:
    if mid_rate <= 0:
        raise ValueError("mid_rate must be positive")
    return (mid_rate - provider_rate) / mid_rate * 100


def provider_rate_from_markup(mid_rate: float, markup: float) -> float:
    return mid_rate * (1 - markup / 100)


def orient_rate(rate: float, mid_rate: float) -> tuple[float, bool]:
    """Express a quoted rate in the same direction as `mid_rate` (receive units per send unit).

    People quote rates both ways ("1 USD = 95.4 INR" vs "1 INR = 0.0105 USD"). Whichever reading is
    closer to the mid rate (on a log scale) is the right one. Returns (rate, was_inverted).
    """
    if rate <= 0 or mid_rate <= 0:
        raise ValueError("rates must be positive")
    direct = abs(math.log(rate / mid_rate))
    inverted = abs(math.log((1 / rate) / mid_rate))
    return (1 / rate, True) if inverted < direct else (rate, False)


def _build(mode: str, entered: float, converted: float, fee: float, provider_rate: float,
           mid_rate: float) -> CostBreakdown:
    if converted < 0:
        raise ValueError("fee exceeds the amount sent")
    m = markup_pct(provider_rate, mid_rate)
    markup_cost = converted * m / 100
    total_cost = fee + markup_cost
    paid = converted + fee
    fee_share = fee / total_cost * 100 if total_cost > 0 else 0.0
    return CostBreakdown(
        mode=mode, entered_amount=entered, amount_converted=converted, fee=fee, total_paid=paid,
        provider_rate=provider_rate, mid_rate=mid_rate,
        amount_received=converted * provider_rate, received_at_mid=paid * mid_rate,
        markup_pct=m, markup_cost=markup_cost, total_cost=total_cost,
        total_cost_pct=total_cost / entered * 100 if entered else 0.0,
        fee_share_pct=fee_share, markup_share_pct=100 - fee_share if total_cost > 0 else 0.0,
    )


def cost_from_budget(budget: float, fee: float, provider_rate: float, mid_rate: float) -> CostBreakdown:
    """The sender hands over `budget`; the fee is deducted before conversion."""
    return _build("budget", budget, budget - fee, fee, provider_rate, mid_rate)


def cost_from_principal(principal: float, fee: float, provider_rate: float, mid_rate: float) -> CostBreakdown:
    """The sender converts `principal` and pays the fee on top (World Bank convention)."""
    return _build("principal", principal, principal, fee, provider_rate, mid_rate)


@dataclass(frozen=True)
class DeliveryCost:
    """Cost of making sure a fixed amount (e.g. a tuition bill) arrives in full."""
    target_amount: float        # receiving currency, must arrive in full
    deducted_on_arrival: float  # receiving currency, intermediary / receiving bank fees
    fee: float                  # sending currency, charged by the provider
    provider_rate: float
    mid_rate: float
    amount_converted: float     # sending currency
    total_paid: float           # sending currency
    fair_cost: float            # sending currency: target at the mid rate with no fees
    markup_pct: float
    markup_cost: float          # sending currency
    total_cost: float           # sending currency: total_paid - fair_cost
    total_cost_pct: float       # % of fair_cost
    total_cost_in_target: float  # total cost expressed in the receiving currency at mid

    def as_dict(self) -> dict:
        return asdict(self)


def cost_to_deliver(target_amount: float, fee: float, provider_rate: float, mid_rate: float,
                    deducted_on_arrival: float = 0.0) -> DeliveryCost:
    """How much the payer spends so that `target_amount` arrives after all deductions."""
    if provider_rate <= 0 or mid_rate <= 0:
        raise ValueError("rates must be positive")
    converted = (target_amount + deducted_on_arrival) / provider_rate
    paid = converted + fee
    fair = target_amount / mid_rate
    m = markup_pct(provider_rate, mid_rate)
    total = paid - fair
    return DeliveryCost(
        target_amount=target_amount, deducted_on_arrival=deducted_on_arrival, fee=fee,
        provider_rate=provider_rate, mid_rate=mid_rate, amount_converted=converted, total_paid=paid,
        fair_cost=fair, markup_pct=m, markup_cost=converted * m / 100, total_cost=total,
        total_cost_pct=total / fair * 100, total_cost_in_target=total * mid_rate,
    )


# ----------------------------------------------------------------- fee schedules

@dataclass(frozen=True)
class LinearSchedule:
    """A value (fee or margin) observed at two amounts, interpolated linearly between them.

    The World Bank surveys each product at ~USD 200 and ~USD 500. Two points identify a
    fixed + percentage fee structure (fee = fixed + rate * amount). Outside the surveyed range the
    result is an extrapolation and is flagged as such.
    """
    a1: float
    v1: float
    a2: float | None = None
    v2: float | None = None
    floor: float | None = 0.0
    hold_outside: bool = False  # True: use the nearest observed value outside the range (margins)

    def at(self, amount: float) -> tuple[float, bool]:
        """Return (value, extrapolated)."""
        if self.a2 is None or self.v2 is None or self.a2 == self.a1:
            return self.v1, not _close(amount, self.a1)
        lo_a, hi_a = sorted((self.a1, self.a2))
        extrapolated = amount < lo_a * 0.999 or amount > hi_a * 1.001
        if self.hold_outside and extrapolated:
            value = self.v1 if abs(amount - self.a1) < abs(amount - self.a2) else self.v2
        else:
            slope = (self.v2 - self.v1) / (self.a2 - self.a1)
            value = self.v1 + slope * (amount - self.a1)
        if self.floor is not None:
            value = max(self.floor, value)
        return value, extrapolated

    @property
    def fixed_part(self) -> float:
        if self.a2 is None or self.v2 is None or self.a2 == self.a1:
            return self.v1
        slope = (self.v2 - self.v1) / (self.a2 - self.a1)
        return self.v1 - slope * self.a1

    @property
    def percent_part(self) -> float:
        if self.a2 is None or self.v2 is None or self.a2 == self.a1:
            return 0.0
        return (self.v2 - self.v1) / (self.a2 - self.a1) * 100


def _close(a: float, b: float, tol: float = 0.001) -> bool:
    return abs(a - b) <= tol * max(abs(a), abs(b), 1)


def _num(x) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN -> None


def schedules_for(row: dict) -> tuple[LinearSchedule, LinearSchedule]:
    """Fee and margin schedules for one RPW product row."""
    a1, a2 = _num(row["amt200_lcu"]), _num(row.get("amt500_lcu"))
    f1, f2 = _num(row["fee200_lcu"]), _num(row.get("fee500_lcu"))
    m1, m2 = _num(row["margin200_pct"]), _num(row.get("margin500_pct"))
    has_500 = a2 is not None and f2 is not None and m2 is not None
    fee = LinearSchedule(a1, f1, a2 if has_500 else None, f2 if has_500 else None, floor=0.0)
    margin = LinearSchedule(a1, m1, a2 if has_500 else None, m2 if has_500 else None, floor=None,
                            hold_outside=True)
    return fee, margin
