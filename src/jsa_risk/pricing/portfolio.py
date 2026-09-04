"""Portfolio-level scenario aggregation — reused by the P&L heatmap, the delta-scenario
table, and the payoff chart instead of each reimplementing this inline.

Both functions layer an *additional* shock on top of the current stress-slider state
(`base_stress`), exactly as the original portfolioPnlAt()/portfolioDeltaAt() did.
"""
from datetime import date
from typing import Callable, Iterable, Optional

from .stress import (
    Position,
    PositionEval,
    StressState,
    days_to_expiry,
    eval_position,
    stressed_future,
    stressed_sigma,
)
from .symbols import canonical_contract_key


def portfolio_pnl_at(
    positions: Iterable[Position],
    get_contract_price: Callable[[str], float],
    base_stress: StressState,
    price_shock_dollars: float,
    vol_shock_pct: float,
    days_fwd: float,
    today: Optional[date] = None,
) -> float:
    total = 0.0
    for p in positions:
        F = stressed_future(get_contract_price(canonical_contract_key(p.label)), base_stress) + price_shock_dollars
        if p.type == "future":
            sigma = 0.5
        else:
            sigma = max(stressed_sigma(p.iv, base_stress) * (1 + vol_shock_pct / 100), 0.5)
        dte = days_to_expiry(p.expiry_date, today)
        T = 0.0 if dte is None else max(dte - base_stress.days - days_fwd, 0) / 365
        r: PositionEval = eval_position(
            p, base_stress, get_contract_price, F_override=F, sigma_override=sigma, T_override=T, today=today
        )
        total += r.pnl
    return total


def portfolio_delta_at(
    positions: Iterable[Position],
    get_contract_price: Callable[[str], float],
    base_stress: StressState,
    price_shock_dollars: float,
    today: Optional[date] = None,
) -> float:
    """Net delta ($, i.e. bushel-equivalent exposure) at a hypothetical price, holding
    vol and time at the current stress scenario (no extra vol/time axis, unlike
    `portfolio_pnl_at`)."""
    total = 0.0
    for p in positions:
        F = stressed_future(get_contract_price(canonical_contract_key(p.label)), base_stress) + price_shock_dollars
        r = eval_position(p, base_stress, get_contract_price, F_override=F, today=today)
        total += r.delta_d
    return total
