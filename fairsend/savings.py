"""Personal savings summary: yearly cost with the current provider vs the cheapest suitable alternative."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

from fairsend import compare

FREQUENCIES = {"Weekly": 52, "Every two weeks": 26, "Monthly": 12, "Every two months": 6, "Quarterly": 4,
               "Twice a year": 2, "Once a year": 1}


@dataclass(frozen=True)
class SavingsSummary:
    transfers_per_year: int
    amount: float
    send_currency: str
    country_currency: str
    current_provider: str | None     # None when the user's provider is unknown (route average used)
    current_cost_per_transfer: float
    best_provider: str
    best_product: str
    best_cost_per_transfer: float
    yearly_cost_current: float
    yearly_cost_best: float
    yearly_savings: float
    yearly_extra_received: float     # receiving currency: how much more reaches the family each year
    basis: str

    @property
    def message(self) -> str:
        if self.yearly_savings <= 0.005:
            return "You're already using the cheapest suitable option on this route."
        return (f"Switching would save you about {self.yearly_savings:,.0f} {self.send_currency} a year "
                f"({self.yearly_extra_received:,.0f} {self.country_currency} more reaching your recipient).")


def _describe(row: pd.Series) -> str:
    parts = [row.get("payment_instrument"), row.get("payout_method"), row.get("speed_label")]
    return ", ".join(p for p in parts if isinstance(p, str) and p)


def summarize(source_code: str, dest_code: str, amount: float, transfers_per_year: int,
              current_provider: str | None, *, payout_methods: list[str] | None = None,
              max_days: float | None = None, conn: sqlite3.Connection | None = None,
              comparison: compare.Comparison | None = None) -> SavingsSummary:
    """Compare the user's provider (its cheapest matching product) with the cheapest suitable product."""
    comp = comparison or compare.compare(source_code, dest_code, amount, payout_methods=payout_methods,
                                         max_days=max_days, conn=conn)
    table = comp.table
    if table.empty:
        raise LookupError("No products match these requirements on this route")
    best = table.iloc[0]
    if current_provider:
        mine = table[table["provider"].str.lower() == current_provider.lower()]
        if mine.empty:
            raise LookupError(f"{current_provider} has no product on this route that matches your requirements")
        current = mine.iloc[0]
        current_cost, current_received = float(current["total_cost"]), float(current["amount_received"])
        basis = f"{current['provider']}'s cheapest matching product ({_describe(current)})"
    else:
        current_cost, current_received = float(table["total_cost"].mean()), float(table["amount_received"].mean())
        basis = "average of all matching products on this route (provider not given)"
    per_transfer_saving = current_cost - float(best["total_cost"])
    return SavingsSummary(
        transfers_per_year=transfers_per_year, amount=amount, send_currency=comp.send_currency,
        country_currency=comp.country_currency, current_provider=current_provider,
        current_cost_per_transfer=current_cost, best_provider=best["provider"], best_product=_describe(best),
        best_cost_per_transfer=float(best["total_cost"]),
        yearly_cost_current=current_cost * transfers_per_year,
        yearly_cost_best=float(best["total_cost"]) * transfers_per_year,
        yearly_savings=per_transfer_saving * transfers_per_year,
        yearly_extra_received=(float(best["amount_received"]) - current_received) * transfers_per_year,
        basis=basis,
    )
