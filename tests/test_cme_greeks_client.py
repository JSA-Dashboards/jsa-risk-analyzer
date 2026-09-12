from unittest.mock import patch

import pytest

from jsa_risk.config import CmeGreeksConfig
from jsa_risk.integrations.cme_greeks_client import (
    CmeGreeksUnavailable,
    _atm_iv,
    _latest_by_contract,
    atm_iv_by_canonical_key,
    fetch_greeks,
)

CONFIG = CmeGreeksConfig(
    api_id="API_TEST",
    password="pw",
    base_url="https://markets.api.cmegroup.test/greeks/v1",
    token_url="https://auth.cmegroup.test/as/token.oauth2",
)


def _leg(strike, pc, iv, delta, stat):
    return {
        "globexSym": f"OZCZ26 {pc}{strike:04.0f}", "strikePx": strike, "putCallInd": pc,
        "optStat": stat, "moneyness": 1.0, "impliedVol": iv, "impliedVolBid": iv - 0.002,
        "impliedVolAsk": iv + 0.002, "theoPx": 20.0, "delta": delta, "gamma": 0.007,
        "theta": -0.15, "vega": 0.91, "rho": -3.8,
    }


def _record(sym, transact_time, legs, undly="ZCZ26", undly_px=527.375, dte=70.4):
    return {
        "businessDt": transact_time[:10], "transactTime": transact_time,
        "modelType": "BsAmericanApprox", "assetClass": "AGRICULTURE",
        "instrument": {
            "exchMic": "XCBT", "productCode": "OZC", "sym": sym,
            "undlyProductCode": "ZC", "undlySym": undly, "undlyPx": undly_px,
            "exerStyle": "Amer", "dte": dte,
        },
        "values": legs,
    }


# --- /latest returns several snapshots per contract, not one moment in time ---

def test_latest_by_contract_keeps_only_the_newest_snapshot_per_contract():
    recs = [
        _record("OZCZ26", "2026-09-08T12:31:01Z", [_leg(525, "C", 0.20, 0.53, "ATM")]),
        _record("OZCZ26", "2026-09-11T09:06:01Z", [_leg(525, "C", 0.2332, 0.53, "ATM")]),
        _record("OZCN27", "2026-09-11T09:06:01Z", [_leg(560, "C", 0.2152, 0.51, "ATM")]),
    ]
    kept = _latest_by_contract(recs)
    assert len(kept) == 2
    z26 = [r for r in kept if r["instrument"]["sym"] == "OZCZ26"]
    assert len(z26) == 1
    assert z26[0]["transactTime"] == "2026-09-11T09:06:01Z"


def test_latest_by_contract_handles_empty_input():
    assert _latest_by_contract([]) == []
    assert _latest_by_contract(None) == []


# --- ATM selection ---

def test_atm_iv_averages_the_atm_call_and_put():
    legs = [_leg(525, "C", 0.2332, 0.53, "ATM"), _leg(525, "P", 0.2312, -0.47, "ATM")]
    iv, method = _atm_iv(legs)
    assert iv == pytest.approx(0.2322)
    assert method == "ATM"


def test_atm_iv_falls_back_to_nearest_50_delta_and_says_so():
    """A thin contract may have no ATM strike with a two-sided market."""
    legs = [_leg(700, "C", 0.31, 0.12, "OTM"), _leg(540, "C", 0.24, 0.47, "OTM")]
    iv, method = _atm_iv(legs)
    assert iv == 0.24
    assert method == "~0.47d"


def test_atm_iv_rejects_a_leg_whose_iv_market_is_too_wide_to_believe():
    """After the 13:20 CT close the book widens but CME still publishes a mid, so the
    number looks authoritative and is not. Corn N27 read 38.55% on a 0.16/0.60 IV
    market, against 21.5% in the session."""
    wide = _leg(600, "C", 0.3855, 0.469, "ATM")
    wide["impliedVolBid"], wide["impliedVolAsk"] = 0.1604, 0.6049
    assert _atm_iv([wide]) is None


def test_atm_iv_accepts_a_normal_session_spread():
    tight = _leg(525, "C", 0.2332, 0.53, "ATM")
    tight["impliedVolBid"], tight["impliedVolAsk"] = 0.2312, 0.2353
    iv, method = _atm_iv([tight])
    assert iv == pytest.approx(0.2332)
    assert method == "ATM"


def test_atm_iv_keeps_a_leg_that_has_no_bid_ask_to_judge():
    leg = _leg(525, "C", 0.2332, 0.53, "ATM")
    leg["impliedVolBid"] = leg["impliedVolAsk"] = None
    assert _atm_iv([leg])[0] == pytest.approx(0.2332)


def test_atm_iv_refuses_a_far_out_of_the_money_leg_as_an_atm_proxy():
    """Live Z28 corn had nothing nearer than 19 delta. Skew makes that vol
    unrepresentative, so it must not be written as the contract's ATM vol."""
    legs = [_leg(700, "C", 0.2114, 0.19, "OTM"), _leg(750, "C", 0.2300, 0.11, "OTM")]
    assert _atm_iv(legs) is None


def test_atm_iv_returns_none_when_no_leg_is_priced():
    assert _atm_iv([]) is None
    assert _atm_iv([{"optStat": "OTM", "strikePx": 600}]) is None


# --- canonical key mapping ---

def _patched(records):
    return patch(
        "jsa_risk.integrations.cme_greeks_client.fetch_latest",
        return_value=records,
    )


def test_atm_iv_by_canonical_key_converts_decimal_to_percent():
    recs = [_record("OZCZ26", "2026-09-11T09:06:01Z",
                    [_leg(525, "C", 0.2332, 0.53, "ATM"), _leg(525, "P", 0.2332, -0.47, "ATM")])]
    with _patched(recs):
        quotes = atm_iv_by_canonical_key(CONFIG)
    assert set(quotes) == {"Z26"}
    # IV_SNAPSHOT stores percent, the API returns a decimal.
    assert quotes["Z26"].iv_pct == pytest.approx(23.32)
    assert quotes["Z26"].as_of == "2026-09-11T09:06:01Z"
    assert quotes["Z26"].option_sym == "OZCZ26"
    assert quotes["Z26"].undly_sym == "ZCZ26"


def test_serial_contracts_are_excluded_so_they_cannot_overwrite_the_quarterly():
    """Oct/Nov corn options both resolve to Z26 in the app's key scheme; if they were
    written to IV_SNAPSHOT they would clobber December's vol with a short-dated one."""
    recs = [
        _record("OZCV26", "2026-09-11T09:06:01Z", [_leg(530, "C", 0.3013, 0.51, "ATM")],
                undly="ZCZ26", dte=14.4),
        _record("OZCX26", "2026-09-11T09:06:01Z", [_leg(530, "C", 0.2541, 0.52, "ATM")],
                undly="ZCZ26", dte=42.4),
        _record("OZCZ26", "2026-09-11T09:06:01Z", [_leg(525, "C", 0.2332, 0.53, "ATM")],
                undly="ZCZ26", dte=70.4),
    ]
    with _patched(recs):
        quotes = atm_iv_by_canonical_key(CONFIG)
    assert set(quotes) == {"Z26"}
    assert quotes["Z26"].option_sym == "OZCZ26"
    assert quotes["Z26"].iv_pct == pytest.approx(23.32)


def test_malformed_symbols_are_skipped_not_crashed_on():
    recs = [
        _record("OZC", "2026-09-11T09:06:01Z", [_leg(525, "C", 0.23, 0.53, "ATM")]),
        _record("OZCZ2X", "2026-09-11T09:06:01Z", [_leg(525, "C", 0.23, 0.53, "ATM")]),
        _record("OZCN27", "2026-09-11T09:06:01Z", [_leg(560, "C", 0.2152, 0.51, "ATM")]),
    ]
    with _patched(recs):
        quotes = atm_iv_by_canonical_key(CONFIG)
    assert set(quotes) == {"N27"}


def test_source_label_records_which_contract_and_snapshot_the_vol_came_from():
    recs = [_record("OZCZ26", "2026-09-11T09:06:01Z", [_leg(525, "C", 0.2332, 0.53, "ATM")])]
    with _patched(recs):
        label = atm_iv_by_canonical_key(CONFIG)["Z26"].source_label
    assert "OZCZ26" in label and "2026-09-11T09:06:01Z" in label
    assert len(label) <= 256  # IV_SNAPSHOT.SOURCE is VARCHAR(256)


# --- per-leg greeks ---

def test_fetch_greeks_picks_the_requested_strike_and_type():
    recs = [_record("OZCZ26", "2026-09-11T09:06:01Z", [
        _leg(525, "C", 0.2332, 0.53, "ATM"),
        _leg(560, "P", 0.2514, -0.31, "OTM"),
    ])]
    with patch("jsa_risk.integrations.cme_greeks_client._get",
               return_value={"payload": recs, "metadata": {}}):
        res = fetch_greeks(CONFIG, "OZCZ26", strike=560, opt_type="put")
    assert res.iv == pytest.approx(0.2514)
    assert res.delta == pytest.approx(-0.31)
    assert res.as_of == "2026-09-11T09:06:01Z"


def test_fetch_greeks_raises_unavailable_when_nothing_comes_back():
    with patch("jsa_risk.integrations.cme_greeks_client._get",
               return_value={"payload": [], "metadata": {}}):
        with pytest.raises(CmeGreeksUnavailable):
            fetch_greeks(CONFIG, "OZCZ26")
