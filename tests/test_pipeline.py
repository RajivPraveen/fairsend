"""Cleaning, currency inference, and data quality checks."""

import pandas as pd
import pytest

from fairsend.pipeline import clean, currency, quality


def test_provider_key_ignores_noise():
    assert clean.provider_key("Al Muzaini Exchange ") == clean.provider_key("Al Muzaini Exchange")
    assert clean.provider_key("NetFox Ltd") == clean.provider_key("Netfox")
    assert clean.provider_key("Trans-Fast") == clean.provider_key("Transfast")
    assert clean.provider_key("Tonga Ma'ae Tonga") == clean.provider_key("Tonga Maae Tonga")


def test_standardize_providers_and_networks():
    raw = pd.Series(["Transferwise", "Wise", "Wise", "La Poste via Western Union", "Ameer Tech Remittance (MoneyGram)",
                     "Habib Express ", "Habib Express"])
    provider, network = clean.standardize_providers(raw)
    assert provider.tolist()[:3] == ["Wise", "Wise", "Wise"]
    assert network.tolist()[3] == "Western Union"
    assert network.tolist()[4] == "MoneyGram"
    assert provider.tolist()[5] == provider.tolist()[6] == "Habib Express"


@pytest.mark.parametrize("raw,expected", [
    ("Cash", "Cash pickup"), ("Bank Account", "Bank account"), ("Own/partner bank account", "Bank account"),
    ("Cash, Bank Account, Home Delivery", "Cash pickup, Bank account, Home delivery"),
    ("ATM Network", "Cash pickup (ATM)"), ("Mobile wallet", "Mobile wallet"), (None, "Unknown"),
])
def test_standardize_payout(raw, expected):
    assert clean.standardize_payout(raw) == expected


def test_firm_type_and_dates():
    assert clean.standardize_firm_type("Money Transfer Operator / Post Office") == "Money Transfer Operator / Post office"
    assert clean.period_to_date(pd.Series(["2025_3Q", "2011_1Q"])).dt.strftime("%Y-%m-%d").tolist() == \
        ["2025-07-01", "2011-01-01"]
    parsed = clean.parse_collected(pd.Series(["24/Jan/2011", pd.Timestamp("2024-05-03")], dtype=object))
    assert parsed.dt.strftime("%Y-%m-%d").tolist() == ["2011-01-24", "2024-05-03"]


def test_nonstandard_currency_codes_fixed():
    ccy, fixed = clean.standardize_send_currency(pd.Series(["CFA", "CFA", "CLF", "usd "]),
                                                 pd.Series(["SEN", "CMR", "CHL", "USA"]))
    assert ccy.tolist() == ["XOF", "XAF", "CLP", "USD"]
    assert fixed.tolist() == [True, True, True, False]


def _row(**kw):
    base = dict(obs_id="v2:1", period_date="2025-07-01", source_code="USA", dest_code="IND", firm_raw="X",
                send_currency="USD", receive_currency="INR", amt200_lcu=200.0, fee200_lcu=5.0, fx_rate200=82.0,
                margin200_pct=1.2048, total200_pct=3.7048, amt500_lcu=500.0, fee500_lcu=5.0, fx_rate500=82.0,
                margin500_pct=1.2048, total500_pct=2.2048, interbank_fx=83.0, transparent=1,
                send_currency_fixed=False, speed_days_max=1.0, ecb_mid_rate=83.1)
    base.update(kw)
    return base


def test_quality_checks_flag_and_invalidate():
    df = pd.DataFrame([
        _row(),                                                         # clean
        _row(obs_id="v2:2", fee200_lcu=-1.0),                           # negative fee -> error
        _row(obs_id="v2:3", total200_pct=150.0),                        # impossible -> error
        _row(obs_id="v2:4", transparent=0, margin200_pct=0.0, total200_pct=2.5),  # non-transparent -> warning
        _row(obs_id="v2:5", receive_currency=None),                     # unmapped -> error
        _row(obs_id="v2:1"),                                            # duplicate -> error
        _row(obs_id="v2:6", ecb_mid_rate=100.0),                        # interbank off ECB -> warning
    ])
    out, results = quality.run_checks(df)
    assert out["is_valid"].tolist() == [1, 0, 0, 1, 0, 0, 1]
    assert out.loc[3, "quality_flags"] == "non_transparent"
    assert "interbank_vs_ecb" in out.loc[6, "quality_flags"]
    by_name = {r["check_name"]: r for r in results}
    assert by_name["negative_fee"]["rows_failed"] == 1
    assert by_name["duplicate_id"]["rows_failed"] == 1
    assert 0 <= by_name["non_transparent"]["pass_rate"] <= 1


def test_payout_currency_inference():
    ecb = pd.DataFrame({
        "rate_date": pd.to_datetime(["2025-08-01"] * 4),
        "base": ["EUR", "EUR", "USD", "KRW"], "quote": ["RON", "USD", "EUR", "USD"],
        "rate": [5.07, 1.14, 0.877, 0.00072],
    }).sort_values("rate_date")
    df = pd.DataFrame({
        "collected_date": ["2025-08-02"] * 4, "period_date": ["2025-07-01"] * 4,
        "dest_code": ["ROU", "ROU", "CHN", "LTU"], "send_currency": ["EUR", "EUR", "KRW", "GBP"],
        "receive_currency": ["RON", "RON", "CNY", "EUR"],
        "interbank_fx": [5.06, 1.0, 0.00071, 1.18],
    })
    out = currency.infer_receive_currency(df, ecb)
    assert out["receive_currency"].tolist()[:3] == ["RON", "EUR", "USD"]
    assert out["payout_currency_basis"].tolist()[1] == "interbank rate = 1"
    # Lithuania used the litas before 2015
    old = currency.country_currency_on(pd.Series(["LTU"]), pd.Series(pd.to_datetime(["2013-05-01"])),
                                       pd.Series(["EUR"]))
    assert old.tolist() == ["LTL"]
