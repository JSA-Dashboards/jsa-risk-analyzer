"""Stress-scenario transforms and the core per-position pricing/P&L function.

Ported from the JSA Risk Analyzer HTML tool's evalPosition(). The critical rule: the
moment any stress slider is non-zero, or a hypothetical F/sigma/T is supplied (used by
the heatmap/delta-scenario/payoff panels to ask "what if"), the last tick is ignored in
favor of the theoretical model price — a tick only stands in for Mark on the live,
unshocked book.
"""
from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

from .black76 import black76

CORN_MULT = 5000
CORN_DAILY_VOL = 0.016


@dataclass(frozen=True)
class Position:
    """A single book entry. `type` is 'call' | 'put' | 'future'; strike/expiry_date/iv
    are None for futures. `qty` is signed (positive = long, negative = short)."""
    id: int
    label: str
    type: str
    qty: int
    entry: float
    strike: Optional[float] = None
    expiry_date: Optional[date] = None
    iv: Optional[float] = None
    iv_estimated: bool = False
    last_tick: Optional[float] = None
    import_mark: Optional[float] = None


@dataclass
class StressState:
    price_pct: float = 0.0
    vol_pct: float = 0.0
    days: float = 0.0

    @property
    def is_neutral(self) -> bool:
        return self.price_pct == 0 and self.vol_pct == 0 and self.days == 0


def days_to_expiry(expiry_date: Optional[date], today: Optional[date] = None) -> Optional[int]:
    if expiry_date is None:
        return None
    today = today or date.today()
    return (expiry_date - today).days


def stressed_future(contract_price: float, stress: StressState) -> float:
    return contract_price * (1 + stress.price_pct / 100)


def stressed_sigma(iv: float, stress: StressState) -> float:
    return max(iv * (1 + stress.vol_pct / 100), 0.5)


def stressed_T(expiry_date: Optional[date], stress: StressState, today: Optional[date] = None) -> float:
    dte = days_to_expiry(expiry_date, today)
    if dte is None:
        return 0.0
    return max(dte - stress.days, 0.0) / 365


@dataclass(frozen=True)
class PositionEval:
    price: float           # Mark actually used for pnl/import_gain (tick or model)
    model_price: float      # theoretical price, always model-based, for reference/hints
    delta_d: float
    gamma_d: float
    vega_d: float
    theta_d: float
    pnl: float              # vs. entry/cost basis
    import_gain: float      # vs. import_mark (falls back to entry if never set)


def eval_position(
    position: Position,
    stress: StressState,
    get_contract_price: Callable[[str], float],
    F_override: Optional[float] = None,
    sigma_override: Optional[float] = None,
    T_override: Optional[float] = None,
    today: Optional[date] = None,
) -> PositionEval:
    from .symbols import canonical_contract_key  # local import avoids a circular dependency

    no_stress = stress.is_neutral
    has_tick = position.last_tick is not None
    use_last_tick = (F_override is None) and no_stress and has_tick

    canonical_key = canonical_contract_key(position.label)
    F = F_override if F_override is not None else stressed_future(get_contract_price(canonical_key), stress)
    pos_mult = position.qty * CORN_MULT
    import_basis = position.import_mark if position.import_mark is not None else position.entry

    if position.type == "future":
        fut_mark = position.last_tick if use_last_tick else F
        return PositionEval(
            price=fut_mark,
            model_price=F,
            delta_d=pos_mult,
            gamma_d=0.0,
            vega_d=0.0,
            theta_d=0.0,
            pnl=(fut_mark - position.entry) * pos_mult,
            import_gain=(fut_mark - import_basis) * pos_mult,
        )

    sigma = sigma_override if sigma_override is not None else stressed_sigma(position.iv, stress)
    T = T_override if T_override is not None else stressed_T(position.expiry_date, stress, today)
    result = black76(F, position.strike, T, sigma, position.type == "call")
    mark = position.last_tick if use_last_tick else result.price

    return PositionEval(
        price=mark,
        model_price=result.price,
        delta_d=result.delta * pos_mult,
        gamma_d=result.gamma * pos_mult,
        vega_d=(result.vega / 100) * pos_mult,
        theta_d=(result.theta / 365) * pos_mult,
        pnl=(mark - position.entry) * pos_mult,
        import_gain=(mark - import_basis) * pos_mult,
    )
