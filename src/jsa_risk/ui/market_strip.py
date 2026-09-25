"""Live market data — manual per-contract price cards (ported from the HTML tool's
`buildMktStrip()`) plus the "Update prices from Massive" button that fills them in
automatically when Massive is configured.
"""
from datetime import datetime
from typing import List, Tuple

import streamlit as st

from jsa_risk.data import audit_repo, reference_repo
from jsa_risk.pricing.stress import Position, effective_underlying_display, effective_underlying_key


def _distinct_contract_groups(positions: List[Position]) -> List[Tuple[str, Position]]:
    """Dedupes by each position's *effective* underlying (its underlying_override if set,
    else the auto-derived one) -- so an Oct option and its Dec future collapse into one
    card, and an overridden position collapses into whatever it was overridden to, not
    whatever its symbol alone would auto-resolve to. Keeps a representative Position per
    group so the card can still show a proper decoded (and override-aware) name."""
    seen = set()
    groups: List[Tuple[str, Position]] = []
    for p in positions:
        key = effective_underlying_key(p)
        if key not in seen:
            seen.add(key)
            groups.append((key, p))
    return groups


def render_market_strip(positions: List[Position]) -> None:
    groups = _distinct_contract_groups(positions)
    if not groups:
        st.caption("No contracts in the book to price.")
        return

    marks = reference_repo.get_contract_marks()
    cols = st.columns(min(len(groups), 4))
    for i, (key, rep_position) in enumerate(groups):
        display_name = effective_underlying_display(rep_position) if rep_position.label else "Corn futures (unlabeled)"
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
    canon_keys = sorted({effective_underlying_key(p) for p in positions})

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
                    # Rerun so the KPIs/Greeks/charts above this section (already rendered
                    # earlier in this same script pass, off the pre-update cached prices)
                    # pick up the fresh marks too -- stash the message since a message shown
                    # right before rerun() never reaches the user.
                    st.session_state["_flash_market_update"] = (
                        f"Updated {len(result.updated)} contract price(s) from Massive{delay_note}: {updated_str}."
                    )
                    st.rerun()
                else:
                    msg_col.warning("No matching contracts returned from Massive.")
    st.caption("Massive futures prices are delayed ~10 minutes — not a real-time or executable quote.")


# Vols come from a scheduled refresh, not from anything the viewer can see happening, so
# the dashboard states their age. STALE_AFTER_DAYS is deliberately short: corn settlement
# vols are published every trading day, so anything older than a long weekend means the
# refresh has stopped rather than the market being quiet.
STALE_AFTER_DAYS = 4


def summarize_iv_provenance(rows, in_book, now, stale_after_days=STALE_AFTER_DAYS) -> dict:
    """Pure half of render_iv_provenance, so the staleness rules are testable without
    Streamlit. Returns {caption, warning, behind}; warning is None when vols are fresh."""
    if not rows:
        return {"caption": None, "warning": None, "behind": []}

    dated = [r for r in rows if r.get("as_of") is not None]
    newest = max((r["as_of"] for r in dated), default=None)
    source = next((r["source"] for r in rows if r.get("source")), "")
    family = (source.split(" ATM")[0].split(" (")[0] or "unknown source").strip()

    bits = [f"**Implied vol:** {family}"]
    if newest is not None:
        bits.append(f"settled {newest:%Y-%m-%d}")
    bits.append(f"{len(rows)} contract(s)")

    warning = None
    if newest is not None:
        age = (now - newest).days
        if age > stale_after_days:
            warning = (f"Implied vols are {age} days old (newest settlement "
                       f"{newest:%Y-%m-%d}). Run scripts/refresh_iv_from_cme.py - "
                       f"positions are being priced off stale vol.")

    # A single contract lagging the rest is the case that actually misprices a position:
    # it looks like a normal number in the blotter with nothing to mark it out.
    behind = []
    if newest is not None and in_book:
        behind = sorted(
            r["key"] for r in rows
            if r["key"] in in_book
            and (r.get("as_of") is None or (newest - r["as_of"]).days > stale_after_days)
        )
    return {"caption": " · ".join(bits), "warning": warning, "behind": behind}


def render_iv_provenance(positions: List[Position]) -> None:
    """One line saying where the implied vols came from and how old they are."""
    try:
        rows = reference_repo.get_iv_provenance()
    except Exception:
        return                                   # never break the dashboard over a caption
    if not rows:
        st.caption(f"Implied vol: no snapshot rows - positions fall back to "
                   f"{reference_repo.DEFAULT_IV:.0f}%.")
        return

    in_book = {effective_underlying_key(p) for p in positions}
    summary = summarize_iv_provenance(rows, in_book, datetime.now())
    if summary["caption"]:
        st.caption(summary["caption"])
    if summary["warning"]:
        st.warning(summary["warning"], icon=":material/warning:")
    if summary["behind"]:
        st.caption(f"Older than the rest, and in your book: {', '.join(summary['behind'])}")
