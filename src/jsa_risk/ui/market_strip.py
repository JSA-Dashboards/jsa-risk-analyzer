"""Live market data — manual per-contract price cards (ported from the HTML tool's
`buildMktStrip()`) plus the "Update prices from Massive" button that fills them in
automatically when Massive is configured.
"""
from typing import List

import streamlit as st

from jsa_risk.data import audit_repo, reference_repo
from jsa_risk.pricing.stress import Position
from jsa_risk.pricing.symbols import canonical_contract_key, contract_display_name


def _distinct_contract_labels(positions: List[Position]) -> List[str]:
    """Dedupes by the *canonical* underlying (so an Oct option and its Dec future collapse
    into one card) but keeps a representative raw label per group, so the card can still
    show a proper decoded name."""
    seen = set()
    order: List[str] = []
    for p in positions:
        key = canonical_contract_key(p.label)
        if key not in seen:
            seen.add(key)
            order.append(p.label)
    return order


def render_market_strip(positions: List[Position]) -> None:
    labels = _distinct_contract_labels(positions)
    if not labels:
        st.caption("No contracts in the book to price.")
        return

    marks = reference_repo.get_contract_marks()
    cols = st.columns(min(len(labels), 4))
    for i, raw_label in enumerate(labels):
        key = canonical_contract_key(raw_label)
        display_name = contract_display_name(raw_label) if raw_label else "Corn futures (unlabeled)"
        widget_key = f"mkt_price_{key}"
        if widget_key not in st.session_state:
            current = marks.get(key)
            st.session_state[widget_key] = float(current) if current is not None else reference_repo.DEFAULT_CONTRACT_PRICE

        def _on_change(k=key, wk=widget_key):
            reference_repo.set_contract_price(k, st.session_state[wk], source="manual")

        with cols[i % len(cols)]:
            st.number_input(
                display_name, step=0.01, format="%.4f", key=widget_key, on_change=_on_change,
                help=f"$/bu — current mark ({key})",
            )


def render_massive_refresh(positions: List[Position]) -> None:
    from jsa_risk.config import get_massive_config
    from jsa_risk.integrations import massive_client

    config = get_massive_config()
    canon_keys = sorted({canonical_contract_key(p.label) for p in positions})

    btn_col, msg_col = st.columns([1, 4])
    clicked = btn_col.button("↻ Update prices from Massive", disabled=config is None)

    if config is None:
        msg_col.caption("Massive isn't configured — add a [massive] block to .streamlit/secrets.toml to enable live prices.")
    elif clicked:
        with st.spinner(f"Fetching {', '.join(canon_keys) or 'nothing'} from Massive…"):
            try:
                result = massive_client.fetch_futures_prices(config, canon_keys)
            except Exception as e:
                audit_repo.log_fetch("massive", "/futures/v1/snapshot", success=False, error_message=str(e))
                msg_col.error(f"Couldn't fetch from Massive: {e}")
            else:
                for key, price in result.updated.items():
                    reference_repo.set_contract_price(key, price, source="massive")
                    st.session_state.pop(f"mkt_price_{key}", None)  # let the card re-seed from the fresh mark
                audit_repo.log_fetch("massive", "/futures/v1/snapshot", success=True, http_status=200)
                if result.updated:
                    delay_note = (
                        " (~10 min delayed)" if result.timeframe == "DELAYED"
                        else (f" ({result.timeframe.lower()})" if result.timeframe else "")
                    )
                    updated_str = ", ".join(f"{k} ${v:.4f}" for k, v in result.updated.items())
                    msg_col.success(f"Updated {len(result.updated)} contract price(s) from Massive{delay_note}: {updated_str}.")
                else:
                    msg_col.warning("No matching contracts returned from Massive.")
    st.caption("Massive futures prices are delayed ~10 minutes — not a real-time or executable quote.")
