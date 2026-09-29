"""Receipt parsing (rule-based path; no LLM or OCR needed)."""

import datetime as dt

import pytest

from fairsend import fx
from fairsend.receipts import checker, extract


@pytest.mark.parametrize("text,value", [("1,234.56", 1234.56), ("1.234,56", 1234.56), ("1,23,456.00", 123456.0),
                                        ("2,99", 2.99), ("15,000", 15000.0), ("₹41,560.00", 41560.0),
                                        ("0.010342", 0.010342), ("abc", None)])
def test_parse_number(text, value):
    assert extract.parse_number(text) == value


@pytest.mark.parametrize("text,ccy,iso", [("2024-05-03", None, "2024-05-03"), ("May 3, 2024", None, "2024-05-03"),
                                          ("03-May-2024", None, "2024-05-03"), ("3 May 2024", None, "2024-05-03"),
                                          ("05/03/2024", "USD", "2024-05-03"), ("03/05/2024", "GBP", "2024-05-03"),
                                          ("25/12/2024", "USD", "2024-12-25"), ("not a date", None, None)])
def test_normalize_date(text, ccy, iso):
    assert extract.normalize_date(text, ccy) == iso


APP_RECEIPT = """BlueRiver Remit
Transfer complete
You sent        $500.00
Transfer fee    $3.99
Total paid      $503.99
Exchange rate   1 USD = 83.1200 INR
Recipient gets  ₹41,560.00
Sent on May 3, 2024
"""

SLIP_RECEIPT = """KITE REMITTANCE
DATE        2023-12-13
PRINCIPAL   USD 1,200.00
CHARGES     USD 1.99
TOTAL       USD 1,201.99
RATE        0.00006423
PAYOUT AMOUNT IDR 18,684,300.00
"""


def test_regex_extract_app_receipt():
    e = extract.complete(extract.regex_extract(APP_RECEIPT))
    assert (e.amount_sent, e.send_currency, e.fee, e.exchange_rate) == (500.0, "USD", 3.99, 83.12)
    assert (e.amount_received, e.receive_currency, e.transfer_date) == (41560.0, "INR", "2024-05-03")
    assert extract.consistency_error(e) < 1e-6


def test_regex_extract_inverted_rate_slip():
    e = extract.extract(SLIP_RECEIPT, use_llm=False)
    assert e.amount_sent == 1200.0 and e.fee == 1.99 and e.receive_currency == "IDR"
    assert e.amount_received == 18684300.0
    assert extract.consistency_error(e) < 0.01   # rate printed as IDR->USD, still consistent


def test_checker_message_uses_mid_rate_on_date():
    e = extract.complete(extract.regex_extract(APP_RECEIPT))
    mid = fx.Rate("USD", "INR", 83.50, dt.date(2024, 5, 3), "test")
    r = checker.check_fields(e, mid_rate=mid)
    # markup = (83.5 - 83.12)/83.5 = 0.45509%; cost = 500 * 0.0045509 = 2.2754
    assert r.markup_pct == pytest.approx(0.455090, abs=1e-5)
    assert r.markup_cost == pytest.approx(2.27545, abs=1e-4)
    assert r.message == "This transfer cost you 2.28 USD in exchange-rate markup, on top of the 3.99 USD fee."


def test_checker_derives_rate_when_missing():
    e = extract.Extraction(amount_sent=200, send_currency="USD", fee=2, amount_received=16500,
                           receive_currency="INR", transfer_date="2024-05-03")
    r = checker.check_fields(e, mid_rate=fx.Rate("USD", "INR", 83.0, dt.date(2024, 5, 3), "test"))
    assert r.rate_derived and r.provider_rate == pytest.approx(82.5)


def test_incomplete_receipt_reports_missing_fields():
    with pytest.raises(checker.IncompleteReceipt) as exc:
        checker.check_fields(extract.Extraction(amount_sent=100))
    assert "send_currency" in exc.value.missing


def test_numbers_not_printed_on_the_receipt_are_dropped():
    text = "Transfer amount: USD 275.00\nFee: USD 4.99\nConversion rate: 53.3947\nDate 2025-01-02"
    ai = extract.Extraction(amount_sent=270.01, fee=4.99, exchange_rate=53.0, send_currency="USD")
    kept = extract.keep_printed(ai, text)
    assert kept.amount_sent is None and kept.exchange_rate is None   # rounded / computed, not printed
    assert kept.fee == 4.99


def test_misread_rate_is_repaired_from_the_amounts():
    text = ("Amount to send 200.00 GBP\nTransfer fee 35.00 GBP\nRate 4 GBP = 166.4242 KES\n"
            "They receive 33,284.84 KES\nDate 24-Apr-2024")
    e = extract.extract(text, use_llm=False)
    assert e.exchange_rate == 166.4242
    assert extract.consistency_error(e) < 0.001


def test_imprecise_printed_rate_uses_the_amounts():
    # A rate printed with few digits (IDR per USD shown as USD per IDR) is refined from the two amounts.
    e = extract.Extraction(amount_sent=1000.0, send_currency="USD", fee=5.0, exchange_rate=0.000065,
                           amount_received=15_300_000.0, receive_currency="IDR", transfer_date="2024-05-03")
    r = checker.check_fields(e, mid_rate=fx.Rate("USD", "IDR", 15_500.0, dt.date(2024, 5, 3), "test"))
    assert r.provider_rate == pytest.approx(15_300.0)
    assert r.markup_pct == pytest.approx((15_500 - 15_300) / 15_500 * 100)
