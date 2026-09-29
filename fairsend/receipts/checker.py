"""Measure the hidden exchange-rate markup on a past transfer."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from fairsend import cost_model, fx
from fairsend.receipts import extract as ex_mod
from fairsend.receipts import ocr


@dataclass(frozen=True)
class ReceiptCheck:
    fields: ex_mod.Extraction
    provider_rate: float          # receive units per send unit
    rate_was_inverted: bool
    rate_derived: bool            # rate computed from amount received / amount sent
    mid_rate: fx.Rate
    markup_pct: float
    markup_cost: float            # sending currency
    fee: float
    total_cost: float
    total_cost_pct: float
    received_at_mid: float        # what the principal would have bought at the mid rate

    @property
    def message(self) -> str:
        cur = self.fields.send_currency
        if self.markup_cost <= 0:
            return (f"This transfer's exchange rate was at or better than the mid-market rate; "
                    f"the only cost was the {self.fee:,.2f} {cur} fee.")
        return (f"This transfer cost you {self.markup_cost:,.2f} {cur} in exchange-rate markup, "
                f"on top of the {self.fee:,.2f} {cur} fee.")


class IncompleteReceipt(ValueError):
    def __init__(self, missing: list[str]):
        super().__init__(f"Could not read: {', '.join(missing)}")
        self.missing = missing


def check_fields(fields: ex_mod.Extraction, conn: sqlite3.Connection | None = None,
                 mid_rate: fx.Rate | None = None) -> ReceiptCheck:
    missing = fields.missing()
    if missing:
        raise IncompleteReceipt(missing)
    mid = mid_rate or fx.get_rate(fields.send_currency, fields.receive_currency, fields.transfer_date, conn=conn)
    derived = False
    implied = fields.amount_received / fields.amount_sent if fields.amount_received and fields.amount_sent else None
    if fields.exchange_rate:
        rate, inverted = cost_model.orient_rate(fields.exchange_rate, mid.rate)
        # The two amounts give the rate the provider actually applied, to more digits than a printed rate
        # (e.g. "0.000065"). Use it when it agrees with the printed rate.
        if implied and abs(implied - rate) / rate < 0.02:
            rate = implied
    else:
        rate, inverted, derived = implied, False, True
    fee = fields.fee or 0.0
    c = cost_model.cost_from_principal(fields.amount_sent, fee, rate, mid.rate)
    return ReceiptCheck(
        fields=fields, provider_rate=rate, rate_was_inverted=inverted, rate_derived=derived, mid_rate=mid,
        markup_pct=c.markup_pct, markup_cost=c.markup_cost, fee=fee, total_cost=c.total_cost,
        total_cost_pct=c.total_cost_pct, received_at_mid=fields.amount_sent * mid.rate,
    )


def check_document(data: bytes, use_llm: bool = True, conn: sqlite3.Connection | None = None
                   ) -> tuple[ocr.OCRResult, ex_mod.Extraction]:
    """OCR + extraction only; the caller shows the fields for confirmation before calling check_fields."""
    text = ocr.extract_text(data)
    return text, ex_mod.extract(text.text, use_llm=use_llm)
