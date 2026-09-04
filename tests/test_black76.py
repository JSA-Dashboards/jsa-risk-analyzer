import math

from jsa_risk.pricing.black76 import RATE, black76


def test_zero_time_call_is_intrinsic_value():
    r = black76(F=5.50, K=5.00, T=0, sigma_pct=25, is_call=True)
    assert r.price == 0.50
    assert r.delta == 1.0
    assert r.gamma == 0.0 and r.vega == 0.0 and r.theta == 0.0


def test_zero_time_put_is_intrinsic_value():
    r = black76(F=4.50, K=5.00, T=0, sigma_pct=25, is_call=False)
    assert r.price == 0.50
    assert r.delta == -1.0


def test_zero_time_out_of_the_money_is_worthless():
    call = black76(F=4.50, K=5.00, T=0, sigma_pct=25, is_call=True)
    put = black76(F=5.50, K=5.00, T=0, sigma_pct=25, is_call=False)
    assert call.price == 0.0 and call.delta == 0.0
    assert put.price == 0.0 and put.delta == 0.0


def test_put_call_parity_holds():
    # Black-76 parity: call - put == df*(F-K), independent of sigma.
    F, K, T, sigma = 5.20, 5.00, 0.25, 22.0
    call = black76(F, K, T, sigma, is_call=True)
    put = black76(F, K, T, sigma, is_call=False)
    df = math.exp(-RATE * T)
    assert math.isclose(call.price - put.price, df * (F - K), rel_tol=1e-9, abs_tol=1e-9)


def test_gamma_and_vega_identical_for_call_and_put():
    F, K, T, sigma = 5.20, 5.00, 0.25, 22.0
    call = black76(F, K, T, sigma, is_call=True)
    put = black76(F, K, T, sigma, is_call=False)
    assert math.isclose(call.gamma, put.gamma, rel_tol=1e-9)
    assert math.isclose(call.vega, put.vega, rel_tol=1e-9)


def test_atm_call_delta_is_near_half_times_discount():
    F = K = 5.00
    T, sigma = 0.25, 22.0
    r = black76(F, K, T, sigma, is_call=True)
    df = math.exp(-RATE * T)
    # At F==K, d1 = sigma*sqrt(T)/2 > 0, so delta is a touch above 0.5*df.
    assert 0.5 * df < r.delta < 0.55 * df


def test_price_is_reproducible_from_first_principles():
    """Recompute d1/d2/price independently (math.erf-based normCDF) to catch first-
    principles regressions in the scipy-based implementation."""
    F, K, T, sigma_pct = 5.35, 5.00, 0.5, 24.0
    sigma = sigma_pct / 100
    sqrt_t = math.sqrt(T)
    d1 = (math.log(F / K) + (sigma * sigma / 2) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    def norm_cdf(x):
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    df = math.exp(-RATE * T)
    expected_price = df * (F * norm_cdf(d1) - K * norm_cdf(d2))

    r = black76(F, K, T, sigma_pct, is_call=True)
    assert math.isclose(r.price, expected_price, rel_tol=1e-9)


def test_theta_matches_the_documented_simplified_formula():
    """Theta here is intentionally non-standard (no discrete r*K*e^-rT*N(d2) term) —
    this pins the exact formula so a future "textbook fix" doesn't land silently."""
    F, K, T, sigma_pct = 5.35, 5.00, 0.5, 24.0
    r = black76(F, K, T, sigma_pct, is_call=True)
    sigma = sigma_pct / 100
    sqrt_t = math.sqrt(T)
    d1 = (math.log(F / K) + (sigma * sigma / 2) * T) / (sigma * sqrt_t)
    df = math.exp(-RATE * T)
    pdf1 = math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi)
    expected_theta = RATE * r.price - (F * df * pdf1 * sigma) / (2 * sqrt_t)
    assert math.isclose(r.theta, expected_theta, rel_tol=1e-9)
