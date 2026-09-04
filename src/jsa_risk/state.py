"""Session-state schema for the JSA Risk Analyzer.

As of Phase 2, positions and contract marks are Snowflake-backed (see
`data/positions_repo.py` / `data/reference_repo.py`) — this module now just owns the
per-viewer, session-only stress scenario, plus a cached read-through for the live book
so the blotter isn't re-querying Snowflake on every widget interaction within one run.
"""
from typing import List

import streamlit as st

from jsa_risk.data import positions_repo, reference_repo
from jsa_risk.pricing.stress import Position, StressState


def init_session_state() -> None:
    """Idempotent — safe to call at the top of every page."""
    if "stress" not in st.session_state:
        st.session_state.stress = StressState()


@st.cache_data(ttl=15, show_spinner=False)
def _load_positions_cached() -> List[Position]:
    return positions_repo.load_positions()


def refresh_positions() -> None:
    """Call after any write (blotter edit, delete, import commit) so the next read
    reflects it immediately instead of waiting out the cache TTL."""
    _load_positions_cached.clear()


def visible_positions() -> List[Position]:
    """Phase 2 has no blotter filters yet (that's Phase 3) — every position is visible."""
    return _load_positions_cached()


def get_contract_price(canonical_key: str) -> float:
    return reference_repo.get_contract_price(canonical_key)
