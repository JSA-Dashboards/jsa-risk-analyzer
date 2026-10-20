from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from jsa_risk.config import MassiveConfig
from jsa_risk.integrations import massive_client
from jsa_risk.integrations.massive_client import BASIS_LAST, BASIS_SETTLE, BASIS_SETTLE_MISSING, pick_price
from jsa_risk.pricing.commodities import CORN, LIVE_CATTLE
from jsa_risk.pricing.market_hours import market_is_open

CT = ZoneInfo("America/Chicago")


def ct(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=CT)


# 2026-10-16 is a Friday; 10-19 the following Monday.
@pytest.mark.parametrize("when,corn,cattle", [
    (ct(2026, 10, 16, 10), True, True),        # Friday day session
    (ct(2026, 10, 16, 13, 30), True, True),    # past the 1:20 close, before the 2:00 cutoff
    (ct(2026, 10, 16, 14, 36), False, False),  # after 2pm: closed
    (ct(2026, 10, 16, 19, 30), False, False),  # Friday night: no session
    (ct(2026, 10, 17, 12), False, False),      # Saturday
    (ct(2026, 10, 18, 18), False, False),      # Sunday before the open
    (ct(2026, 10, 18, 19, 30), True, False),   # Sunday night: grains open, cattle never
    (ct(2026, 10, 19, 6), True, False),        # Monday small hours
    (ct(2026, 10, 19, 8), False, False),       # the 7:45-8:30 break
    (ct(2026, 10, 19, 9), True, True),
    (ct(2026, 10, 19, 22), True, False),       # Monday overnight
])
def test_market_hours(when, corn, cattle):
    assert market_is_open(CORN, when) is corn
    assert market_is_open(LIVE_CATTLE, when) is cattle


def test_a_holiday_is_closed_all_day():
    assert market_is_open(CORN, ct(2026, 12, 25, 10)) is False     # Christmas, a Friday


def test_a_utc_clock_is_read_as_central():
    utc = datetime(2026, 10, 16, 19, 36, tzinfo=ZoneInfo("UTC"))  # 2:36 pm Central
    assert market_is_open(CORN, utc) is False


# As Massive sends it after the close: settlement_price just repeats the live price; the
# official settle is previous_settlement.
ROW = {"last_trade": {"price": 462.25}, "session": {"settlement_price": 462.25, "previous_settlement": 461.5}}


def test_open_market_takes_the_last_trade():
    assert pick_price(ROW, use_settlement=False) == (462.25, BASIS_LAST)


def test_closed_market_takes_the_official_settle_not_the_live_price_field():
    assert pick_price(ROW, use_settlement=True) == (461.5, BASIS_SETTLE)


def test_the_live_cattle_case_from_the_dashboard():
    row = {"last_trade": {"price": 231.075},
           "session": {"settlement_price": 231.075, "previous_settlement": 230.875, "close": 231.075}}
    assert pick_price(row, use_settlement=True) == (230.875, BASIS_SETTLE)
    assert pick_price(row, use_settlement=False) == (231.075, BASIS_LAST)


def test_closed_market_with_no_settlement_falls_back_and_says_so():
    row = {"last_trade": {"price": 462.25}, "session": {}}
    assert pick_price(row, use_settlement=True) == (462.25, BASIS_SETTLE_MISSING)


def test_an_implausible_settlement_is_not_marked_into_the_book():
    row = {"last_trade": {"price": 462.25}, "session": {"previous_settlement": 4.61}}   # wrong units
    assert pick_price(row, use_settlement=True) == (462.25, BASIS_SETTLE_MISSING)


def test_fetch_converts_cents_and_reports_basis_per_contract():
    payload = {"status": "OK", "results": [
        {"details": {"ticker": "ZCZ6"}, **ROW},
        {"details": {"ticker": "ZCH7"}, "last_trade": {"price": 470.0}, "session": {}},
    ]}
    cfg = MassiveConfig(api_key="k", base_url="https://example.invalid")
    with patch.object(massive_client, "_fetch_json", return_value=payload):
        res = massive_client.fetch_futures_prices(cfg, ["Z26", "H27"], "ZC", use_settlement=True)
    assert res.updated == {"Z26": pytest.approx(4.615), "H27": pytest.approx(4.70)}
    assert res.basis == {"Z26": BASIS_SETTLE, "H27": BASIS_SETTLE_MISSING}


def test_fetch_reports_what_massive_sent_for_each_contract():
    payload = {"status": "OK", "results": [{"details": {"ticker": "ZCZ6"}, **ROW}]}
    cfg = MassiveConfig(api_key="k", base_url="https://example.invalid")
    with patch.object(massive_client, "_fetch_json", return_value=payload):
        res = massive_client.fetch_futures_prices(cfg, ["Z26"], "ZC", use_settlement=True)
    d = res.detail["Z26"]
    assert (d["last_trade"], d["settlement_price"], d["previous_settlement"]) == (462.25, 462.25, 461.5)
    assert d["used"] == BASIS_SETTLE and "settlement_price" in d["session_fields"]


def test_massive_meal_prices_are_dollars_per_ton_and_stay_that_way():
    payload = {"status": "OK", "results": [
        {"details": {"ticker": "ZMZ6"}, "last_trade": {"price": 312.4}, "session": {"previous_settlement": 311.0}}]}
    cfg = MassiveConfig(api_key="k", base_url="https://example.invalid")
    with patch.object(massive_client, "_fetch_json", return_value=payload):
        res = massive_client.fetch_futures_prices(cfg, ["Z26"], "ZM", price_divisor=1.0)
        closed = massive_client.fetch_futures_prices(cfg, ["Z26"], "ZM", use_settlement=True, price_divisor=1.0)
    assert res.updated == {"Z26": pytest.approx(312.4)}
    assert closed.updated == {"Z26": pytest.approx(311.0)}
