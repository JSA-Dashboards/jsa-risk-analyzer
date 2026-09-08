"""The position blotter. Phase 1 renders it read-only (`st.dataframe`); Phase 2 swaps
the render call for `st.data_editor` and wires edits back through `positions_repo` —
`build_blotter_dataframe` (the shared column computation) doesn't need to change for that.
"""
from typing import Callable, List

import pandas as pd
import streamlit as st

from jsa_risk.pricing.stress import Position, StressState, eval_position
from jsa_risk.pricing.symbols import canonical_contract_key, contract_display_name


def build_blotter_dataframe(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
) -> pd.DataFrame:
    rows = []
    for p in positions:
        r = eval_position(p, stress, get_contract_price)
        dte = None
        if p.expiry_date is not None:
            from datetime import date
            dte = (p.expiry_date - date.today()).days
        rows.append({
            "id": p.id,
            "Contract": p.label,
            "Underlying": contract_display_name(p.label),
            "Type": p.type,
            "Strike": p.strike,
            "DTE (d)": dte,
            "Qty": p.qty,
            "IV%": p.iv,
            "Entry": p.entry,
            "Mark": round(r.price, 4),
            "Delta (bu)": round(r.delta_d),
            "Gamma $": round(r.gamma_d),
            "Vega $": round(r.vega_d),
            "Theta $/d": round(r.theta_d),
            "P&L": round(r.pnl),
            "Gain since import": round(r.import_gain),
            "Delete": False,
        })
    return pd.DataFrame(rows)


_COMPUTED_COLUMN_CONFIG = {
    "Strike": st.column_config.NumberColumn(format="$%.2f"),
    "Entry": st.column_config.NumberColumn(format="$%.4f"),
    "Mark": st.column_config.NumberColumn(format="$%.4f"),
    "Gamma $": st.column_config.NumberColumn(format="$%d"),
    "Vega $": st.column_config.NumberColumn(format="$%d"),
    "Theta $/d": st.column_config.NumberColumn(format="$%d"),
    "P&L": st.column_config.NumberColumn(format="$%d"),
    "Gain since import": st.column_config.NumberColumn(format="$%d"),
}


def render_blotter(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
) -> None:
    df = build_blotter_dataframe(positions, stress, get_contract_price).drop(columns=["id", "Delete"])
    st.dataframe(df, hide_index=True, use_container_width=True, column_config=_COMPUTED_COLUMN_CONFIG)


def render_editable_blotter(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
) -> None:
    """Qty and Entry are editable and write straight through to this session's book; row
    deletion via the Delete checkbox. Full per-column filter/sort and richer cell editing
    (DTE, Mark/last-tick) are a possible later pass."""
    from jsa_risk import state

    df = build_blotter_dataframe(positions, stress, get_contract_price)
    editor_key = "blotter_editor"

    edited = st.data_editor(
        df,
        hide_index=True,
        use_container_width=True,
        key=editor_key,
        disabled=[c for c in df.columns if c not in ("Qty", "Entry", "Delete")],
        column_config={**_COMPUTED_COLUMN_CONFIG, "id": None},
    )

    changes = st.session_state[editor_key]
    edited_rows = changes.get("edited_rows", {}) if isinstance(changes, dict) else {}
    to_delete = []
    wrote_any = False
    for row_idx_str, edits in edited_rows.items():
        row_idx = int(row_idx_str)
        position_id = int(df.iloc[row_idx]["id"])
        if edits.get("Delete"):
            to_delete.append(position_id)
            continue
        if "Qty" in edits:
            state.update_position_field(position_id, "QTY", int(edits["Qty"]))
            wrote_any = True
        if "Entry" in edits:
            state.update_position_field(position_id, "ENTRY", float(edits["Entry"]))
            wrote_any = True

    if to_delete:
        for pid in to_delete:
            state.delete_position(pid)
        st.rerun()
    elif wrote_any:
        st.rerun()


def render_import_gain_summary(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
) -> None:
    evals = [eval_position(p, stress, get_contract_price) for p in positions]
    total_gain = sum(e.import_gain for e in evals)
    sign = "-" if total_gain < 0 else ""
    st.markdown(
        f"**Gain / loss since import**  \n"
        f"### {sign}${abs(total_gain):,.0f}\n"
        f"<span style='font-size:11.5px;color:#898781'>Vs. the Mark each position was imported "
        f"(or added) with — not vs. entry cost. This is the open-position mark-to-market move "
        f"since your last import.</span>",
        unsafe_allow_html=True,
    )
