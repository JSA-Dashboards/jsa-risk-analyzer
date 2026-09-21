"""Tests for the DataMine EOD client.

Fixtures are synthetic rows in the real file's column layout. The real settlement file is
licensed CME data and deliberately not committed to the repo.
"""
import gzip
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from jsa_risk.config import CmeDataMineConfig
import jsa_risk.integrations.cme_datamine_client as dm
from jsa_risk.integrations.cme_datamine_client import (
    CmeDataMineUnavailable,
    FileNotPosted,
    atm_iv_by_canonical_key,
    download_eod,
    file_id,
    latest_available,
    parse_eod_csv,
)

CONFIG = CmeDataMineConfig(
    api_id="api_test", password="pw",
    base_url="https://datamine.new.cmegroup.test/cme/api/v2",
    token_url="https://auth.cmegroup.test/as/token.oauth2",
)

HEADER = ("Trade Date,Exchange Code,Product Code,Put/Call,Strike Price,Contract Year,"
          "Contract Month,Contract Day,Settlement,Open Interest,Delta,Implied Volatility,"
          "Last Trade Date")


def _row(pc, strike, year, month, settle, delta, iv, last="20261120", day="00", td="20260918"):
    return f"{td},XCBT,PY,{pc},{strike},{year},{month},{day},{settle},100,{delta},{iv},{last}"


def _csv(*rows):
    return "\n".join((HEADER,) + rows) + "\n"


@pytest.fixture(autouse=True)
def _clear_token_cache():
    dm._token_cache.clear()
    yield
    dm._token_cache.clear()


# --- file ids ---------------------------------------------------------------------------

def test_file_id_matches_the_product_page_pattern():
    assert file_id(date(2026, 9, 18), "F") == "20260918-EOD_XCBT_PY_OPT_0_ETH_F"
    assert file_id(date(2026, 9, 18), "P") == "20260918-EOD_XCBT_PY_OPT_0_ETH_P"


def test_early_settlement_is_refused_because_it_has_no_iv():
    with pytest.raises(ValueError):
        file_id(date(2026, 9, 18), "E")


# --- ATM selection ----------------------------------------------------------------------

DEC_26 = (
    _row("C", 525, 2026, 12, 205, 0.54, 0.2170),
    _row("P", 525, 2026, 12, 180, 0.46, 0.2180),   # put delta unsigned, as CME publishes it
    _row("C", 530, 2026, 12, 177, 0.497, 0.2160),
    _row("P", 530, 2026, 12, 203, 0.503, 0.2166),
    _row("C", 535, 2026, 12, 152, 0.45, 0.2150),
    _row("P", 535, 2026, 12, 228, 0.55, 0.2155),
)


def test_picks_strike_by_call_delta_and_averages_call_and_put_iv():
    q = atm_iv_by_canonical_key(parse_eod_csv(_csv(*DEC_26)), "P")["Z26"]
    assert q.atm_strike == 530
    assert q.iv_pct == pytest.approx((0.2160 + 0.2166) / 2 * 100)
    assert q.method == "ATM C+P"
    assert q.settlement == "P"


def test_unsigned_put_deltas_do_not_hijack_the_atm_choice():
    # If put deltas were read as signed, a 0.503 put would look like -0.503 and a naive
    # "nearest to 0.5 in absolute terms across all legs" could land on the wrong strike.
    rows = parse_eod_csv(_csv(*DEC_26))
    assert atm_iv_by_canonical_key(rows)["Z26"].atm_strike == 530


def test_underlying_price_comes_from_put_call_parity_in_tenths_of_a_cent():
    q = atm_iv_by_canonical_key(parse_eod_csv(_csv(*DEC_26)))["Z26"]
    assert q.undly_px == pytest.approx(530 + (177 - 203) / 10)   # 527.4
    assert q.undly_sym == "ZCZ26"


def test_dte_is_calendar_days_from_trade_date_to_last_trade_date():
    q = atm_iv_by_canonical_key(parse_eod_csv(_csv(*DEC_26)))["Z26"]
    assert q.trade_date == date(2026, 9, 18)
    assert q.dte == (date(2026, 11, 20) - date(2026, 9, 18)).days


def test_serial_months_are_dropped_so_they_cannot_collide_on_the_quarterly_key():
    rows = parse_eod_csv(_csv(
        *DEC_26,
        _row("C", 530, 2026, 10, 63, 0.49, 0.30, last="20260925"),   # Oct serial on Dec
        _row("C", 530, 2026, 11, 135, 0.49, 0.25, last="20261023"),  # Nov serial on Dec
    ))
    quotes = atm_iv_by_canonical_key(rows)
    assert set(quotes) == {"Z26"}
    assert quotes["Z26"].iv_pct == pytest.approx(21.63)


def test_contract_that_is_nowhere_near_the_money_is_skipped_not_guessed():
    rows = parse_eod_csv(_csv(
        _row("C", 700, 2027, 3, 20, 0.08, 0.30, last="20270219"),
        _row("C", 650, 2027, 3, 40, 0.30, 0.26, last="20270219"),    # 0.20 from ATM
    ))
    assert atm_iv_by_canonical_key(rows) == {}


def test_near_but_not_at_the_money_is_labelled_with_its_delta():
    rows = parse_eod_csv(_csv(_row("C", 560, 2027, 7, 300, 0.41, 0.21, last="20270625")))
    q = atm_iv_by_canonical_key(rows)["N27"]
    assert q.method == "~0.41d"
    assert q.undly_px is None                 # no put at that strike, so no parity price


def test_blank_iv_rows_like_the_early_file_produce_nothing():
    rows = parse_eod_csv(_csv(
        _row("C", 530, 2026, 12, 177, 0.497, ""),
        _row("P", 530, 2026, 12, 203, 0.503, "0"),
    ))
    assert atm_iv_by_canonical_key(rows) == {}


def test_non_standard_expiry_day_is_ignored():
    rows = parse_eod_csv(_csv(_row("C", 530, 2026, 12, 177, 0.497, 0.2160, day="15")))
    assert atm_iv_by_canonical_key(rows) == {}


def test_source_label_names_the_settlement_and_trade_date():
    q = atm_iv_by_canonical_key(parse_eod_csv(_csv(*DEC_26)), "F")["Z26"]
    assert "Final" in q.source_label and "2026-09-18" in q.source_label


# --- download / not-posted handling -----------------------------------------------------

def _token_response():
    r = MagicMock(status_code=200)
    r.json.return_value = {"access_token": "tok", "expires_in": 1799}
    r.raise_for_status.return_value = None
    return r


def _get_response(status, content=b"", json_body=None):
    r = MagicMock(status_code=status, content=content, text=content.decode("latin-1"))
    if json_body is not None:
        r.json.return_value = json_body
    else:
        r.json.side_effect = ValueError("no json")
    return r


def _not_found(detail):
    return _get_response(404, b"{}", {"status": 404, "errors": [{"code": 404, "detail": detail}]})


def test_download_decompresses_gzip_and_sends_a_bearer_token():
    body = gzip.compress(_csv(*DEC_26).encode())
    with patch.object(dm.requests, "post", return_value=_token_response()), \
         patch.object(dm.requests, "get", return_value=_get_response(200, body)) as get:
        text = download_eod(CONFIG, date(2026, 9, 18), "P")
    assert text.startswith("Trade Date,")
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"
    assert get.call_args.kwargs["params"] == {"fid": "20260918-EOD_XCBT_PY_OPT_0_ETH_P"}


def test_file_not_found_404_means_not_posted_yet():
    with patch.object(dm.requests, "post", return_value=_token_response()), \
         patch.object(dm.requests, "get", return_value=_not_found("File not found")):
        with pytest.raises(FileNotPosted):
            download_eod(CONFIG, date(2026, 9, 18), "F")


def test_bad_path_404_is_an_error_not_a_missing_file():
    with patch.object(dm.requests, "post", return_value=_token_response()), \
         patch.object(dm.requests, "get",
                      return_value=_not_found("The requested URL was not found on the server.")):
        with pytest.raises(CmeDataMineUnavailable) as exc:
            download_eod(CONFIG, date(2026, 9, 18), "F")
    assert not isinstance(exc.value, FileNotPosted)


def test_unauthorised_is_reported_as_unavailable():
    with patch.object(dm.requests, "post", return_value=_token_response()), \
         patch.object(dm.requests, "get", return_value=_get_response(401, b"nope")):
        with pytest.raises(CmeDataMineUnavailable):
            download_eod(CONFIG, date(2026, 9, 18), "F")


# --- latest_available -------------------------------------------------------------------

def test_latest_prefers_a_newer_preliminary_over_an_older_final_and_skips_weekends():
    posted = {
        "20260918-EOD_XCBT_PY_OPT_0_ETH_P": gzip.compress(b"friday prelim"),
        "20260917-EOD_XCBT_PY_OPT_0_ETH_F": gzip.compress(b"thursday final"),
    }
    requested = []

    def fake_get(url, params, headers, timeout):
        requested.append(params["fid"])
        if params["fid"] in posted:
            return _get_response(200, posted[params["fid"]])
        return _not_found("File not found")

    with patch.object(dm.requests, "post", return_value=_token_response()), \
         patch.object(dm.requests, "get", side_effect=fake_get):
        d, s, text = latest_available(CONFIG, today=date(2026, 9, 20))   # a Sunday

    assert (d, s, text) == (date(2026, 9, 18), "P", "friday prelim")
    assert requested == ["20260918-EOD_XCBT_PY_OPT_0_ETH_F", "20260918-EOD_XCBT_PY_OPT_0_ETH_P"]
    assert not any(f.startswith(("20260919", "20260920")) for f in requested)


def test_latest_raises_when_nothing_is_posted_in_the_window():
    with patch.object(dm.requests, "post", return_value=_token_response()), \
         patch.object(dm.requests, "get", return_value=_not_found("File not found")):
        with pytest.raises(FileNotPosted):
            latest_available(CONFIG, today=date(2026, 9, 18), lookback_days=2)
