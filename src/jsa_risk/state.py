"""Session-state schema and seed data for the JSA Risk Analyzer.

Phase 1 keeps the book in `st.session_state` only (no Snowflake yet — that lands in
Phase 2), so this module owns: the seed positions (matching the original HTML tool's
10-row demo book), the default contract-mark store, and the current stress scenario.
"""
from datetime import date, timedelta
from typing import Dict, List

import streamlit as st

from jsa_risk.pricing.stress import Position, StressState


def _in_days(n: int) -> date:
    return date.today() + timedelta(days=n)


def _seed_positions() -> List[Position]:
    return [
        Position(id=1, label="ZCU26", type="call", qty=-30, entry=0.21, strike=5.00,
                 expiry_date=_in_days(32), iv=25.20, iv_estimated=True, last_tick=0.020),
        Position(id=2, label="ZCU26", type="put", qty=30, entry=0.19, strike=4.30,
                 expiry_date=_in_days(32), iv=25.20, iv_estimated=True),
        Position(id=3, label="ZCU26", type="call", qty=15, entry=0.18, strike=4.70,
                 expiry_date=_in_days(32), iv=25.20, iv_estimated=True),
        Position(id=4, label="ZCZ26", type="put", qty=20, entry=0.22, strike=4.50,
                 expiry_date=_in_days(95), iv=23.43, iv_estimated=True),
        Position(id=5, label="ZCZ26", type="call", qty=-20, entry=0.15, strike=4.90,
                 expiry_date=_in_days(95), iv=23.43, iv_estimated=True),
        Position(id=6, label="ZCU26", type="future", qty=10, entry=4.55, last_tick=4.6525),
        Position(id=7, label="ZCZ26", type="future", qty=-8, entry=4.80),
        Position(id=8, label="ZCN27", type="call", qty=12, entry=0.24, strike=4.60,
                 expiry_date=_in_days(220), iv=21.50, iv_estimated=True),
        Position(id=9, label="ZCN27", type="future", qty=6, entry=4.50),
        Position(id=10, label="ZCV26", type="put", qty=10, entry=0.17, strike=4.55,
                 expiry_date=_in_days(63), iv=23.43, iv_estimated=True),
    ]


def _seed_contract_prices() -> Dict[str, float]:
    # Demo-only starting marks (Phase 1 has no Massive/manual-entry UI wired up yet).
    return {"U26": 5.15, "Z26": 5.3925, "N27": 5.625}


def init_session_state() -> None:
    """Idempotent — safe to call at the top of every page."""
    if "positions" not in st.session_state:
        st.session_state.positions = _seed_positions()
    if "contract_prices" not in st.session_state:
        st.session_state.contract_prices = _seed_contract_prices()
    if "stress" not in st.session_state:
        st.session_state.stress = StressState()
    if "next_id" not in st.session_state:
        st.session_state.next_id = 11


def get_contract_price(canonical_key: str, default: float = 4.62) -> float:
    return st.session_state.contract_prices.get(canonical_key, default)


def visible_positions() -> List[Position]:
    """Phase 1 has no blotter filters yet (that's Phase 3) — every position is visible."""
    return st.session_state.positions
