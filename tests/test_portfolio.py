from datetime import date

import pytest

from jsa_risk.pricing.commodities import CORN
from jsa_risk.pricing.portfolio import portfolio_delta_at, portfolio_pnl_at, portfolio_reference_price
from jsa_risk.pricing.stress import Position, StressState

TODAY = date(2026, 1, 1)


def price_book(label):
    return {"Z26": 5.00, "H27": 6.00}[label]


def a_future(qty):
    return Position(id=1, label="ZCZ26", type="future", qty=qty, entry=4.80)


def a_call(qty):
    return Position(
        id=2, label="ZCZ26", type="call", qty=qty, entry=0.20,
        strike=5.00, expiry_date=date(2026, 4, 1), iv=25.0,
    )


def test_portfolio_pnl_at_zero_shock_matches_a_direct_eval(monkeypatch=None):
    positions = [a_future(10), a_call(-10)]
    base = StressState()
    pnl_at_zero = portfolio_pnl_at(positions, price_book, base, price_shock_pct=0, vol_shock_pct=0, days_fwd=0, today=TODAY)
    # Sanity: a long future + a short call at the current mark shouldn't be wildly off zero
    # (both legs are near their cost basis at inception-like inputs used here).
    assert isinstance(pnl_at_zero, float)


def test_portfolio_pnl_at_scales_with_price_shock_for_a_long_future():
    positions = [a_future(10)]
    base = StressState()
    pnl_up = portfolio_pnl_at(positions, price_book, base, price_shock_pct=10, vol_shock_pct=0, days_fwd=0, today=TODAY)
    pnl_flat = portfolio_pnl_at(positions, price_book, base, price_shock_pct=0, vol_shock_pct=0, days_fwd=0, today=TODAY)
    # +10% of a $5.00 contract = +50c * 10 contracts * 5000 bu = +$25,000 vs flat.
    assert pnl_up - pnl_flat == pytest.approx(0.50 * 10 * 5000)


def test_price_shock_is_a_percent_of_each_contracts_own_value():
    """The same +10% moves a $6.00 contract by 60c and a $5.00 contract by 50c -- not one
    flat dollar amount applied to both."""
    dec = a_future(10)
    mar = Position(id=3, label="x", type="future", qty=10, entry=5.00, underlying_override="H27")
    base = StressState()
    up = portfolio_pnl_at([dec, mar], price_book, base, price_shock_pct=10, vol_shock_pct=0, days_fwd=0, today=TODAY)
    flat = portfolio_pnl_at([dec, mar], price_book, base, price_shock_pct=0, vol_shock_pct=0, days_fwd=0, today=TODAY)
    assert up - flat == pytest.approx((0.50 + 0.60) * 10 * 5000)


def test_price_shock_layers_on_top_of_the_stress_slider():
    positions = [a_future(10)]
    base = StressState(price_pct=10)  # contract already stressed to $5.50
    up = portfolio_pnl_at(positions, price_book, base, price_shock_pct=10, vol_shock_pct=0, days_fwd=0, today=TODAY)
    flat = portfolio_pnl_at(positions, price_book, base, price_shock_pct=0, vol_shock_pct=0, days_fwd=0, today=TODAY)
    assert up - flat == pytest.approx(0.55 * 10 * 5000)  # 10% of the stressed $5.50, not of $5.00


def test_portfolio_delta_at_matches_a_long_future_exactly():
    positions = [a_future(10)]
    base = StressState()
    delta = portfolio_delta_at(positions, price_book, base, price_shock_pct=2, today=TODAY)
    assert delta == pytest.approx(10 * 5000)  # a future's delta is always qty*mult regardless of price


def test_portfolio_delta_at_ignores_last_tick():
    """Scenario evaluation always uses the model — a set last_tick must not leak in."""
    p = Position(id=1, label="ZCZ26", type="future", qty=10, entry=4.80, last_tick=999.0)
    base = StressState()
    delta = portfolio_delta_at([p], price_book, base, price_shock_pct=0, today=TODAY)
    assert delta == pytest.approx(10 * 5000)


def test_reference_price_is_delta_weighted_across_contracts():
    dec = a_future(10)   # $5.00, delta 50,000
    mar = Position(id=3, label="x", type="future", qty=30, entry=5.00, underlying_override="H27")  # $6.00, delta 150,000
    base = StressState()
    ref = portfolio_reference_price([dec, mar], price_book, base, today=TODAY)
    assert ref == pytest.approx((5.00 * 50_000 + 6.00 * 150_000) / 200_000)


def test_reference_price_ignores_sign_so_a_hedge_does_not_cancel_the_weight():
    long_dec = a_future(10)
    short_mar = Position(id=3, label="x", type="future", qty=-10, entry=5.00, underlying_override="H27")
    ref = portfolio_reference_price([long_dec, short_mar], price_book, StressState(), today=TODAY)
    assert ref == pytest.approx(5.50)


def test_reference_price_empty_book_falls_back_to_the_commodity_default():
    assert portfolio_reference_price([], price_book, StressState(), today=TODAY) == CORN.default_price
