from datetime import date, timedelta
from unittest.mock import patch

import numpy as np
import pytest

from jsa_risk.config import MassiveConfig
from jsa_risk.integrations import massive_client
from jsa_risk.pricing.commodities import CORN
from jsa_risk.pricing.stress import Position, StressState, eval_position
from jsa_risk.pricing.var import Z_95, log_returns
from jsa_risk.ui import kpi

CFG = MassiveConfig(api_key="k", base_url="https://api.massive.test")


def bar(day, settle=None, close=None):
    b = {"session_end_date": day}
    if settle is not None:
        b["settlement_price"] = settle
    if close is not None:
        b["close"] = close
    return b


def test_daily_settles_use_the_settlement_and_fall_back_to_the_close():
    payload = {"status": "OK", "results": [bar("2026-10-14", settle=462.0, close=463.0),
                                           bar("2026-10-15", close=461.0)]}
    with patch.object(massive_client, "_fetch_json", return_value=payload) as f:
        got = massive_client.fetch_daily_settles(CFG, "Z26", "ZC", since=date(2025, 1, 1))
    assert got == {date(2026, 10, 14): 462.0, date(2026, 10, 15): 461.0}
    url, params = f.call_args.args
    assert url.endswith("/futures/v1/aggs/ZCZ6")
    assert params["resolution"] == "1session" and params["window_start.gte"] == "2025-01-01"


def test_daily_settles_leave_out_today_and_follow_pagination():
    pages = [{"results": [bar("2026-10-14", settle=462.0)], "next_url": "https://api.massive.test/next?c=1"},
             {"results": [bar("2026-10-15", settle=461.0), bar("2026-10-16", settle=460.0)]}]
    with patch.object(massive_client, "_fetch_json", side_effect=pages) as f:
        got = massive_client.fetch_daily_settles(CFG, "Z26", "ZC", before=date(2026, 10, 16))
    assert sorted(got) == [date(2026, 10, 14), date(2026, 10, 15)]
    assert f.call_args.args[0] == "https://api.massive.test/next?c=1"


def test_daily_settles_raise_on_a_failed_request_so_nothing_empty_is_cached():
    with patch.object(massive_client, "_fetch_json", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            massive_client.fetch_daily_settles(CFG, "Z26", "ZC")


def _history(vol=0.012, n=200, seed=2):
    rng = np.random.default_rng(seed)
    p = 460 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    return log_returns({date(2025, 1, 1) + timedelta(i): float(p[i]) for i in range(n)})


def test_the_var_exposure_is_priced_in_dollars_not_bushels():
    """100 contracts of corn is 500,000 bu; at $4.62 and ~1.2% a day that is real money, not
    the bushel count times a fraction (the old calculation understated it by the price)."""
    book = [Position(id=1, label="ZCZ26", type="future", qty=100, entry=4.50)]
    stress, price = StressState(), (lambda key: 4.62)
    evals = [eval_position(p, stress, price, commodity=CORN) for p in book]
    hist = _history()
    with patch("jsa_risk.data.price_history.get_return_history", return_value=({"Z26": hist}, "")):
        result, problem = kpi.compute_book_var(book, evals, stress, price, CORN)
    assert problem == "" and result.method == "covariance"
    dollars = 500_000 * 4.62
    assert result.contracts[0].exposure == pytest.approx(dollars)
    assert result.var > Z_95 * dollars * 0.004          # nowhere near the old bushels-only figure
    assert result.var == pytest.approx(Z_95 * dollars * result.contracts[0].daily_vol)


def test_options_count_by_their_delta_not_their_notional():
    book = [Position(id=1, label="ZCZ26", type="call", qty=10, entry=0.2, strike=5.5,
                     expiry_date=date.today() + timedelta(60), iv=22.0)]
    stress, price = StressState(), (lambda key: 4.62)
    evals = [eval_position(p, stress, price, commodity=CORN) for p in book]
    with patch("jsa_risk.data.price_history.get_return_history", return_value=({"Z26": _history()}, "")):
        result, _ = kpi.compute_book_var(book, evals, stress, price, CORN)
    assert result.contracts[0].exposure == pytest.approx(evals[0].delta_d * 4.62)
    assert abs(result.contracts[0].exposure) < 0.5 * 50_000 * 4.62     # far out of the money


def test_a_history_failure_falls_back_to_the_assumed_vol_and_says_why():
    book = [Position(id=1, label="ZCZ26", type="future", qty=10, entry=4.50)]
    stress, price = StressState(), (lambda key: 4.62)
    evals = [eval_position(p, stress, price, commodity=CORN) for p in book]
    with patch("jsa_risk.data.price_history.get_return_history", side_effect=RuntimeError("down")):
        result, problem = kpi.compute_book_var(book, evals, stress, price, CORN)
    assert result.method == "fixed" and "down" in problem
    assert result.var == pytest.approx(Z_95 * 50_000 * 4.62 * CORN.daily_vol)


def test_an_empty_book_makes_no_history_request():
    with patch("jsa_risk.data.price_history.get_return_history") as hist:
        result, problem = kpi.compute_book_var([], [], StressState(), lambda k: 4.62, CORN)
    hist.assert_not_called()
    assert result.var == 0 and problem == ""
