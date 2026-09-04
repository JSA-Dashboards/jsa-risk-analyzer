"""KPI strip: Net Position, Net Gamma $, Net Vega $, Net Theta $/day, 1-Day 95% VaR —
computed over whichever positions are currently visible (all of them, until Phase 3
adds blotter filters)."""
from typing import Callable, List

import streamlit as st

from jsa_risk.pricing.stress import Position, StressState, eval_position
from jsa_risk.pricing.var import CORN_DAILY_VOL, value_at_risk


def _fmt_bu(v: float) -> str:
    av = abs(v)
    if av >= 1e6:
        return f"{av / 1e6:.2f}M bu"
    if av >= 1e3:
        return f"{av / 1e3:.1f}K bu"
    return f"{av:.0f} bu"


def _fmt_dollars(v: float) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.0f}"


def render_kpi_strip(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
) -> None:
    evals = [eval_position(p, stress, get_contract_price) for p in positions]
    net_delta = sum(e.delta_d for e in evals)
    net_gamma = sum(e.gamma_d for e in evals)
    net_vega = sum(e.vega_d for e in evals)
    net_theta = sum(e.theta_d for e in evals)
    var_95 = value_at_risk(net_delta)

    direction = "LONG" if net_delta > 0 else ("SHORT" if net_delta < 0 else "FLAT")
    contracts = abs(net_delta) / 5000

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Net Position", f"{direction} {_fmt_bu(net_delta)}", help=f"≈{contracts:.1f} contracts")
    c2.metric("Net Gamma $", _fmt_dollars(net_gamma), help="Δdelta per $1 move")
    c3.metric("Net Vega $", _fmt_dollars(net_vega), help="per 1 vol pt")
    c4.metric("Net Theta $/day", _fmt_dollars(net_theta), help="time decay")
    c5.metric("1-Day 95% VaR", _fmt_dollars(-var_95), help="delta-normal")


def render_var_panel(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
) -> None:
    evals = [eval_position(p, stress, get_contract_price) for p in positions]
    net_delta = sum(e.delta_d for e in evals)
    var_95 = value_at_risk(net_delta)
    st.metric("1-Day 95% VaR", _fmt_dollars(-var_95))
    st.caption(
        f"Delta-normal: 1.645 × |net delta $| × an assumed {CORN_DAILY_VOL * 100:.1f}% daily corn futures move."
    )
