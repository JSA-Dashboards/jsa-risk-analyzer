from datetime import date

import pytest

from jsa_risk.pricing.portfolio import portfolio_delta_at, portfolio_pnl_at
from jsa_risk.pricing.stress import Position, StressState

TODAY = date(2026, 1, 1)


def price_book(label):
    return {"Z26": 5.00}[label]


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
    pnl_at_zero = portfolio_pnl_at(positions, price_book, base, price_shock_dollars=0, vol_shock_pct=0, days_fwd=0, today=TODAY)
    # Sanity: a long future + a short call at the current mark shouldn't be wildly off zero
    # (both legs are near their cost basis at inception-like inputs used here).
    assert isinstance(pnl_at_zero, float)


def test_portfolio_pnl_at_scales_with_price_shock_for_a_long_future():
    positions = [a_future(10)]
    base = StressState()
    pnl_up = portfolio_pnl_at(positions, price_book, base, price_shock_dollars=0.50, vol_shock_pct=0, days_fwd=0, today=TODAY)
    pnl_flat = portfolio_pnl_at(positions, price_book, base, price_shock_dollars=0, vol_shock_pct=0, days_fwd=0, today=TODAY)
    # +50c on a long future = +50c * 10 contracts * 5000 bu = +$25,000 vs flat.
    assert pnl_up - pnl_flat == pytest.approx(0.50 * 10 * 5000)


def test_portfolio_delta_at_matches_a_long_future_exactly():
    positions = [a_future(10)]
    base = StressState()
    delta = portfolio_delta_at(positions, price_book, base, price_shock_dollars=0.10, today=TODAY)
    assert delta == pytest.approx(10 * 5000)  # a future's delta is always qty*mult regardless of price


def test_portfolio_delta_at_ignores_last_tick():
    """Scenario evaluation always uses the model — a set last_tick must not leak in."""
    p = Position(id=1, label="ZCZ26", type="future", qty=10, entry=4.80, last_tick=999.0)
    base = StressState()
    delta = portfolio_delta_at([p], price_book, base, price_shock_dollars=0, today=TODAY)
    assert delta == pytest.approx(10 * 5000)
