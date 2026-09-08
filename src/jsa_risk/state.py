"""Session-state schema for the JSA Risk Analyzer.

The book is session-only: this app is shared with customers via a public URL, and
positions are the customer's own hypothetical/actual holdings, not a shared JSA book — so
each browser session gets its own private copy, never written to Snowflake, never visible
to any other session. (An earlier Phase 2 briefly made positions Snowflake-backed for a
single-internal-user assumption that no longer holds once the app went out to customers;
`data/positions_repo.py` and the POSITIONS/IMPORT_BATCHES/POSITION_HISTORY tables are kept
around unused, in case a separate internal-only view is wanted later.)

Reference data — contract marks, IV snapshot, prior settles, import presets — stays
Snowflake-backed via `data/reference_repo.py` / `data/presets_repo.py`: that's real shared
market data and format templates, not customer-specific, so it's correct for every session
to see the same values.
"""
from dataclasses import replace
from datetime import date, timedelta
from typing import List, Optional

import streamlit as st

from jsa_risk.data import reference_repo
from jsa_risk.pricing.stress import Position, StressState


def _in_days(n: int) -> date:
    return date.today() + timedelta(days=n)


def _default_positions() -> List[Position]:
    """The same 10-position demo book the original HTML tool always opened with —
    customers see a populated, explorable example before pasting/adding their own."""
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


def init_session_state() -> None:
    """Idempotent — safe to call at the top of every page."""
    if "stress" not in st.session_state:
        st.session_state.stress = StressState()
    if "positions" not in st.session_state:
        st.session_state.positions = _default_positions()
        st.session_state.next_position_id = 11


def visible_positions() -> List[Position]:
    """No blotter filters yet (that's a later pass) — every session-local position is
    visible."""
    return st.session_state.positions


def add_position(p: Position) -> int:
    new_id = st.session_state.next_position_id
    st.session_state.next_position_id += 1
    st.session_state.positions.append(replace(p, id=new_id))
    return new_id


def update_position_field(position_id: int, field: str, value) -> None:
    field_map = {
        "LABEL": "label", "TYPE": "type", "STRIKE": "strike", "EXPIRY_DATE": "expiry_date",
        "QTY": "qty", "IV": "iv", "IV_ESTIMATED": "iv_estimated", "ENTRY": "entry",
        "LAST_TICK": "last_tick",
    }
    attr = field_map.get(field, field.lower())
    positions = st.session_state.positions
    for i, p in enumerate(positions):
        if p.id == position_id:
            positions[i] = replace(p, **{attr: value})
            return


def delete_position(position_id: int) -> None:
    st.session_state.positions = [p for p in st.session_state.positions if p.id != position_id]


def replace_book(positions: List[Position]) -> int:
    """Replaces the whole session-local book — assigns fresh sequential ids, matching the
    "importing replaces the whole book" UX carried over from the original tool. Returns
    the count of positions replaced (there's no batch/history table anymore, so nothing
    else to hand back)."""
    next_id = 1
    numbered = []
    for p in positions:
        numbered.append(replace(p, id=next_id))
        next_id += 1
    st.session_state.positions = numbered
    st.session_state.next_position_id = next_id
    return len(numbered)


def get_contract_price(canonical_key: str) -> float:
    return reference_repo.get_contract_price(canonical_key)
