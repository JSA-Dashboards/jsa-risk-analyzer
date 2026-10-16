import math

import pytest

from jsa_risk.pricing.black76 import RATE, american, black76


def _crr(F, K, T, sigma_pct, is_call, n=1000):
    """Cox-Ross-Rubinstein binomial tree on a future (no carry) -- the benchmark."""
    s = sigma_pct / 100
    dt = T / n
    u = math.exp(s * math.sqrt(dt))
    d = 1 / u
    disc = math.exp(-RATE * dt)
    p = (1 - d) / (u - d)
    sign = 1 if is_call else -1
    vals = [max(sign * (F * u**j * d**(n - j) - K), 0) for j in range(n + 1)]
    for i in range(n - 1, -1, -1):
        vals = [max(disc * (p * vals[j + 1] + (1 - p) * vals[j]), sign * (F * u**j * d**(i - j) - K))
                for j in range(i + 1)]
    return vals[0]


CASES = [
    (4.62, 4.60, 0.20, 22, True), (4.62, 4.60, 0.20, 22, False),
    (4.62, 5.20, 0.50, 25, False), (4.62, 4.00, 0.50, 25, True),
    (2.40, 2.60, 0.10, 18, False), (10.5, 9.0, 0.30, 20, True),
]


@pytest.mark.parametrize("F,K,T,sigma,is_call", CASES)
def test_matches_a_binomial_tree(F, K, T, sigma, is_call):
    assert american(F, K, T, sigma, is_call).price == pytest.approx(_crr(F, K, T, sigma, is_call), rel=1e-3, abs=3e-4)


@pytest.mark.parametrize("F,K,T,sigma,is_call", CASES)
def test_never_below_european_or_intrinsic(F, K, T, sigma, is_call):
    a = american(F, K, T, sigma, is_call).price
    assert a >= black76(F, K, T, sigma, is_call).price - 1e-12
    assert a >= (max(F - K, 0) if is_call else max(K - F, 0)) - 1e-12


def test_deep_in_the_money_option_is_worth_at_least_its_intrinsic_value():
    # European puts here are below intrinsic (discounting); the American is not.
    F, K = 2.0, 2.6
    assert black76(F, K, 0.3, 20, False).price < K - F
    assert american(F, K, 0.3, 20, False).price == pytest.approx(K - F, abs=1e-9)


def test_exact_at_expiry_and_for_non_positive_inputs():
    assert american(5.5, 5.0, 0, 25, True).price == pytest.approx(0.5)
    assert american(4.5, 5.0, 0, 25, False).price == pytest.approx(0.5)
    assert american(0.0, 4.5, 0.25, 20.0, True).price == 0.0


def test_greeks_have_sensible_signs_and_size():
    c = american(4.62, 4.60, 0.2, 22, True)
    p = american(4.62, 4.60, 0.2, 22, False)
    e = black76(4.62, 4.60, 0.2, 22, True)
    assert 0 < c.delta < 1 and -1 < p.delta < 0
    assert c.gamma > 0 and c.vega > 0 and c.theta < 0
    assert c.delta == pytest.approx(e.delta, abs=0.02)
    assert c.vega == pytest.approx(e.vega, rel=0.05)
    assert c.theta == pytest.approx(e.theta, rel=0.08)
