"""Portfolio-level scenario aggregation — reused by the P&L heatmap, the delta-scenario
table, and the payoff chart instead of each reimplementing this inline.

Both functions layer an *additional* shock on top of the current stress-slider state
(`base_stress`), exactly as the original portfolioPnlAt()/portfolioDeltaAt() did. The
price shock is expressed as a percent of the book's reference price (see
portfolio_reference_price) but applied as ONE parallel move: every contract shifts by the
same cents per unit. That keeps a delta-neutral book flat -- a book long and short the same
number of bushels/pounds across differently-priced contracts has no P&L from a parallel
move, whatever the contracts' own prices. (An earlier version scaled the shock by each
contract's own price, which tilted a unit-neutral book by the price difference between its
legs.)
"""
from datetime import date
from typing import Callable, Iterable, Optional

from .commodities import CORN, CommoditySpec
from .stress import (
    Position,
    PositionEval,
    StressState,
    days_to_expiry,
    effective_underlying_key,
    eval_position,
    stressed_future,
    stressed_sigma,
)


def _shocked_future(
    position: Position,
    get_contract_price: Callable[[str], float],
    base_stress: StressState,
    price_shock_pct: float,
    today: Optional[date],
    commodity: CommoditySpec,
    ref_price: float,
) -> float:
    base_F = stressed_future(get_contract_price(effective_underlying_key(position, today, commodity)), base_stress)
    return base_F + price_shock_pct / 100 * ref_price


def portfolio_reference_price(
    positions: Iterable[Position],
    get_contract_price: Callable[[str], float],
    base_stress: StressState,
    today: Optional[date] = None,
    commodity: CommoditySpec = CORN,
) -> float:
    """One representative underlying price for the whole book, in the commodity's own unit
    ($/bu or $/lb), used to translate a % price shock into an equivalent cents-per-unit
    label. Weighted by |delta| so the contracts carrying the most exposure dominate; falls
    back to a plain average when every delta is zero, and to the commodity's default price
    for an empty book."""
    prices, weights = [], []
    for p in positions:
        prices.append(stressed_future(get_contract_price(effective_underlying_key(p, today, commodity)), base_stress))
        weights.append(abs(eval_position(p, base_stress, get_contract_price, today=today, commodity=commodity).delta_d))
    if not prices:
        return commodity.default_price
    total = sum(weights)
    if total <= 0:
        return sum(prices) / len(prices)
    return sum(f * w for f, w in zip(prices, weights)) / total


def portfolio_pnl_at(
    positions: Iterable[Position],
    get_contract_price: Callable[[str], float],
    base_stress: StressState,
    price_shock_pct: float,
    vol_shock_pct: float,
    days_fwd: float,
    today: Optional[date] = None,
    commodity: CommoditySpec = CORN,
    ref_price: Optional[float] = None,
) -> float:
    positions = list(positions)
    if ref_price is None:
        ref_price = portfolio_reference_price(positions, get_contract_price, base_stress, today, commodity)
    total = 0.0
    for p in positions:
        F = _shocked_future(p, get_contract_price, base_stress, price_shock_pct, today, commodity, ref_price)
        if p.type == "future":
            sigma = 0.5
        else:
            sigma = max(stressed_sigma(p.iv, base_stress) * (1 + vol_shock_pct / 100), 0.5)
        dte = days_to_expiry(p.expiry_date, today)
        T = 0.0 if dte is None else max(dte - base_stress.days - days_fwd, 0) / 365
        r: PositionEval = eval_position(
            p, base_stress, get_contract_price, F_override=F, sigma_override=sigma, T_override=T, today=today,
            commodity=commodity,
        )
        total += r.pnl
    return total



def mark_offset(
    positions: Iterable[Position],
    get_contract_price: Callable[[str], float],
    base_stress: StressState,
    today: Optional[date] = None,
    commodity: CommoditySpec = CORN,
    ref_price: Optional[float] = None,
) -> float:
    """What the book is worth right now, less what the model says it is worth right now.

    `portfolio_pnl_at` always reprices off Black-76 -- it has to, since a shocked scenario
    cannot be marked to a frozen tick. The blotter does the opposite at zero stress and
    prefers an imported `last_tick`. Left alone, that makes the scenario grid's own zero
    cell disagree with the P&L column above it, and the two can be far apart.

    Adding this offset to a scenario value re-bases it onto the blotter's mark: the tick
    is trusted for what the position is worth NOW, the model only for how that value
    MOVES. The grid shifts bodily; its shape, and every greek behind it, is untouched.

    Returns 0.0 whenever no tick is in play -- an unmarked book, or any non-neutral
    stress, where `eval_position` drops the tick too.
    """
    positions = list(positions)
    marked = sum(
        eval_position(p, base_stress, get_contract_price, today=today, commodity=commodity).pnl
        for p in positions
    )
    modelled = portfolio_pnl_at(
        positions, get_contract_price, base_stress, 0, 0, 0, today, commodity, ref_price,
    )
    return marked - modelled


def portfolio_delta_at(
    positions: Iterable[Position],
    get_contract_price: Callable[[str], float],
    base_stress: StressState,
    price_shock_pct: float,
    today: Optional[date] = None,
    commodity: CommoditySpec = CORN,
    ref_price: Optional[float] = None,
) -> float:
    """Net delta ($, i.e. unit-equivalent exposure) at a hypothetical price, holding
    vol and time at the current stress scenario (no extra vol/time axis, unlike
    `portfolio_pnl_at`)."""
    positions = list(positions)
    if ref_price is None:
        ref_price = portfolio_reference_price(positions, get_contract_price, base_stress, today, commodity)
    total = 0.0
    for p in positions:
        F = _shocked_future(p, get_contract_price, base_stress, price_shock_pct, today, commodity, ref_price)
        r = eval_position(p, base_stress, get_contract_price, F_override=F, today=today, commodity=commodity)
        total += r.delta_d
    return total
