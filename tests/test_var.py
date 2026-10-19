from datetime import date, timedelta

import numpy as np
import pytest

from jsa_risk.pricing.var import (
    Z_95,
    book_var,
    ewma_covariance,
    key_order,
    log_returns,
    value_at_risk,
)


def test_var_is_z_times_exposure_times_daily_vol():
    assert value_at_risk(net_delta_d=100_000) == pytest.approx(1.645 * 100_000 * 0.016)


def test_var_is_symmetric_in_sign_of_delta():
    assert value_at_risk(net_delta_d=-100_000) == value_at_risk(net_delta_d=100_000)


def test_var_is_zero_for_flat_delta():
    assert value_at_risk(net_delta_d=0) == 0


def test_var_scales_with_custom_inputs():
    assert value_at_risk(net_delta_d=50_000, daily_vol=0.02, z=2.0) == pytest.approx(2.0 * 50_000 * 0.02)


# --- covariance VaR ----------------------------------------------------------------------

D0 = date(2025, 1, 1)
N = 300


def _prices(returns, start=0):
    p = 100 * np.exp(np.cumsum(returns))
    return {D0 + timedelta(i): float(p[i]) for i in range(start, len(returns))}


def _book_history(seed=1, idio=0.004):
    """Three contracts sharing a common factor (corr ~0.9); K27 is a young contract."""
    rng = np.random.default_rng(seed)
    common = rng.normal(0, 0.012, N)

    def one(start=0):
        return log_returns(_prices(common + rng.normal(0, idio, N), start))

    return {"Z26": one(), "H27": one(), "K27": one(start=285)}


HIST = _book_history()


def test_log_returns_skip_bad_prices():
    r = log_returns({date(2026, 1, 1): 100.0, date(2026, 1, 2): 0.0, date(2026, 1, 3): 110.0})
    assert list(r) == [date(2026, 1, 3)] and r[date(2026, 1, 3)] == pytest.approx(np.log(1.1))


def test_a_hedged_spread_has_far_less_var_than_either_leg():
    outright = book_var({"Z26": 1e6}, HIST, 0.016).var
    spread = book_var({"Z26": 1e6, "H27": -1e6}, HIST, 0.016).var
    assert 0 < spread < 0.7 * outright           # not zero: the legs are not perfectly correlated


def test_a_spread_is_not_free_the_way_net_delta_would_say():
    assert value_at_risk(0.0) == 0
    assert book_var({"Z26": 1e6, "H27": -1e6}, HIST, 0.016).var > 0


def test_same_direction_legs_add_up_to_nearly_the_sum():
    both = book_var({"Z26": 1e6, "H27": 1e6}, HIST, 0.016).var
    one = book_var({"Z26": 1e6}, HIST, 0.016).var
    assert 1.7 * one < both <= 2 * one + 1e-6


def test_component_vars_sum_to_the_book_var():
    r = book_var({"Z26": 1e6, "H27": -4e5, "K27": 2e5}, HIST, 0.016)
    assert sum(c.component_var for c in r.contracts) == pytest.approx(r.var)


def test_a_young_contract_borrows_the_nearest_contracts_vol_and_says_so():
    r = book_var({"K27": 1e6}, HIST, 0.016, min_obs=30)
    c = r.contracts[0]
    assert c.proxy == "H27" and c.observations == 0
    assert any("K27" in n and "H27" in n for n in r.notes)
    assert r.var == pytest.approx(book_var({"H27": 1e6}, HIST, 0.016).var)


def test_no_usable_history_falls_back_to_the_fixed_vol_on_net_exposure():
    r = book_var({"Z26": 1e6, "H27": -4e5}, {}, 0.016)
    assert r.method == "fixed" and r.fixed_vol == 0.016
    assert r.var == pytest.approx(Z_95 * 6e5 * 0.016)


def test_an_empty_or_flat_book_is_zero():
    assert book_var({}, HIST, 0.016).var == 0
    assert book_var({"Z26": 0.0}, HIST, 0.016).var == 0


def test_ewma_weights_recent_days_more_than_a_flat_average():
    # Quiet year, then a violent last week: EWMA vol must sit well above the whole-sample vol.
    rng = np.random.default_rng(3)
    r = np.concatenate([rng.normal(0, 0.005, 250), rng.normal(0, 0.03, 10)])
    series = {"Z26": log_returns(_prices(r))}
    _, cov = ewma_covariance(series)
    assert np.sqrt(cov[0, 0]) > 2 * r.std()


def test_the_matrix_is_repaired_to_positive_semidefinite():
    # Pairwise overlap on ragged histories can produce a slightly indefinite matrix.
    rng = np.random.default_rng(5)
    base = rng.normal(0, 0.01, 200)
    hist = {
        "F26": log_returns(_prices(base + rng.normal(0, 0.003, 200))),
        "H26": log_returns(_prices(base + rng.normal(0, 0.003, 200), start=100)),
        "K26": log_returns(_prices(-base + rng.normal(0, 0.003, 200), start=50)),
    }
    _, cov = ewma_covariance(hist)
    assert np.linalg.eigvalsh(cov).min() >= -1e-12


def test_key_order_is_calendar_order():
    assert sorted(["H27", "Z26", "F27", "K26"], key=key_order) == ["K26", "Z26", "F27", "H27"]
