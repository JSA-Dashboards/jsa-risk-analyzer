from datetime import date, timedelta

import streamlit as st

from jsa_risk.data import positions_repo
from jsa_risk.pricing.black76 import black76
from jsa_risk.pricing.stress import Position
from jsa_risk.pricing.symbols import canonical_contract_key, contract_display_name
from jsa_risk.state import get_contract_price, refresh_positions

CORN_MULT = 5000
DEFAULT_CONTRACT_PRICE = 4.62
INSTRUMENTS = ["call", "put", "future"]


def _fmt_dollars_signed(v: float) -> str:
    sign = "-" if v < 0 else "+"
    return f"{sign}${abs(v):,.0f}"


def _fmt_bu_signed(v: float) -> str:
    sign = "-" if v < 0 else "+"
    return f"{sign}{abs(v):,.0f} bu"


def _default_draft() -> dict:
    return {
        "label": "",
        "type": "call",
        "strike": round(DEFAULT_CONTRACT_PRICE, 2),
        "expiry": date.today() + timedelta(days=60),
        "qty": 10,
        "iv": 25.0,
        "use_model_entry": True,
        "entry": None,
    }


if "add_pos_draft" not in st.session_state:
    st.session_state.add_pos_draft = _default_draft()
draft = st.session_state.add_pos_draft


def _on_type_change() -> None:
    new_type = st.session_state.add_pos_type
    draft["type"] = new_type
    if new_type == "future":
        draft["strike"], draft["expiry"], draft["iv"] = None, None, None
        draft["use_model_entry"] = True
    elif draft.get("strike") is None:
        draft["strike"] = round(get_contract_price(canonical_contract_key(draft["label"])), 2)
        draft["expiry"] = date.today() + timedelta(days=60)
        draft["iv"] = 25.0


st.markdown("###### New position ticket")
st.caption(
    "Priced live against the current corn futures market data — add it and it lands directly "
    "in the blotter."
)

field_col, preview_col = st.columns([3, 2])

with field_col:
    draft["label"] = st.text_input(
        "Contract symbol (required)", value=draft["label"], placeholder="e.g. ZCZ26",
        help="Decoded to the underlying month/year automatically.",
    ).strip()
    st.selectbox(
        "Instrument", INSTRUMENTS, index=INSTRUMENTS.index(draft["type"]),
        key="add_pos_type", on_change=_on_type_change,
        format_func=lambda v: "FUTURE" if v == "future" else v.upper(),
    )
    is_future = draft["type"] == "future"

    if not is_future:
        draft["strike"] = st.number_input(
            "Strike", value=float(draft["strike"] or DEFAULT_CONTRACT_PRICE), step=0.01, format="%.2f",
        )
        draft["expiry"] = st.date_input(
            "Expiration date", value=draft["expiry"] or (date.today() + timedelta(days=60)),
        )

    draft["qty"] = int(st.number_input(
        "Quantity (lots)", value=int(draft["qty"]), step=1, help="+long / -short",
    ))

    if not is_future:
        draft["iv"] = st.number_input("Implied vol %", value=float(draft["iv"] or 25.0), step=0.5)

    draft["use_model_entry"] = st.checkbox(
        "Use current futures mark as entry" if is_future else "Use model price as entry",
        value=draft["use_model_entry"],
    )
    if not draft["use_model_entry"]:
        draft["entry"] = st.number_input(
            "Entry price" if is_future else "Entry premium",
            value=float(draft["entry"]) if draft["entry"] is not None else 0.0,
            step=0.01, format="%.4f",
        )
    else:
        draft["entry"] = None

with preview_col:
    F = get_contract_price(canonical_contract_key(draft["label"]))
    pos_mult = draft["qty"] * CORN_MULT

    if is_future:
        model_price = F
        entry_price = F if draft["entry"] is None else draft["entry"]
        delta_d, gamma_d, vega_d, theta_d = float(pos_mult), 0.0, 0.0, 0.0
        dte = None
    else:
        dte = max((draft["expiry"] - date.today()).days, 0) if draft["expiry"] else 0
        T = dte / 365
        strike = draft["strike"] or 0.0001
        iv = draft["iv"] or 0.01
        result = black76(F, strike, T, iv, draft["type"] == "call")
        model_price = result.price
        entry_price = model_price if draft["entry"] is None else draft["entry"]
        delta_d = result.delta * pos_mult
        gamma_d = result.gamma * pos_mult
        vega_d = (result.vega / 100) * pos_mult
        theta_d = (result.theta / 365) * pos_mult

    pnl = (model_price - entry_price) * pos_mult

    title = (draft["label"] or "Corn") + " " + ("FUTURE" if is_future else f"{draft['type'].upper()} {draft['strike']}")
    st.markdown(f"**{title}**")
    contract_name = f"{draft['label']} futures" if draft["label"] else "Corn futures (no contract picked — using default mark)"
    if is_future:
        sub = f"{contract_name} mark ${F:.3f}/bu · linear exposure, no expiry decay"
    else:
        sub = f"{contract_name} mark ${F:.3f}/bu · strike ${draft['strike'] or 0:.2f} · {dte}d to expiry"
    st.caption(sub)

    c1, c2 = st.columns(2)
    c1.metric("Model price", f"${model_price:.3f}")
    c2.metric("Entry price" if is_future else "Entry premium", f"${entry_price:.3f}")
    c1.metric("Delta (bu)", _fmt_bu_signed(delta_d))
    c2.metric("Gamma $", _fmt_dollars_signed(gamma_d))
    c1.metric("Vega $/vol pt", _fmt_dollars_signed(vega_d))
    c2.metric("Theta $/day", _fmt_dollars_signed(theta_d))
    st.metric("Day-one P&L vs entry", _fmt_dollars_signed(pnl))

st.markdown("---")
submit_col, reset_col, msg_col = st.columns([1, 1, 3])
submit_clicked = submit_col.button("Add to book", type="primary")
reset_clicked = reset_col.button("Clear form")

if reset_clicked:
    st.session_state.add_pos_draft = _default_draft()
    st.rerun()

if submit_clicked:
    error = None
    if not draft["label"]:
        error = "Enter the contract symbol this is against (e.g. ZCZ26) — the strike is meaningless without it."
    elif not is_future and (not draft["strike"] or draft["strike"] <= 0):
        error = "Strike must be greater than 0."
    elif not is_future and draft["expiry"] is None:
        error = "Pick an expiration date."
    elif not is_future and (not draft["iv"] or draft["iv"] <= 0):
        error = "Implied vol must be greater than 0."
    elif not draft["qty"]:
        error = "Quantity can't be zero."

    if error:
        msg_col.error(error)
    else:
        new_position = Position(
            id=0,
            label=draft["label"],
            type=draft["type"],
            qty=draft["qty"],
            entry=entry_price,
            strike=None if is_future else draft["strike"],
            expiry_date=None if is_future else draft["expiry"],
            iv=None if is_future else draft["iv"],
        )
        new_id = positions_repo.add_position(new_position)
        refresh_positions()
        st.session_state["_flash_added"] = f"Added {contract_display_name(draft['label'])} {draft['type']} — position #{new_id}."
        st.switch_page("pages/dashboard.py")
