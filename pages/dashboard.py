import streamlit as st

from jsa_risk.state import get_contract_price, visible_positions
from jsa_risk.ui.blotter import render_blotter, render_import_gain_summary
from jsa_risk.ui.kpi import render_kpi_strip

st.markdown("###### Portfolio risk summary")
positions = visible_positions()
stress = st.session_state.stress

render_kpi_strip(positions, stress, get_contract_price)

st.markdown("---")

st.markdown("###### Stress scenario")
c1, c2, c3, c4 = st.columns([3, 3, 3, 1])
stress.price_pct = c1.slider("Price shock %", -30.0, 30.0, stress.price_pct, 1.0)
stress.vol_pct = c2.slider("Vol shock %", -50.0, 100.0, stress.vol_pct, 5.0)
stress.days = c3.slider("Days forward", 0, 120, int(stress.days), 1)
with c4:
    st.write("")
    st.write("")
    if st.button("Reset"):
        stress.price_pct, stress.vol_pct, stress.days = 0.0, 0.0, 0.0
        st.rerun()

st.markdown("---")

st.markdown("###### Position blotter")
render_import_gain_summary(positions, stress, get_contract_price)
st.write("")
render_blotter(positions, stress, get_contract_price)

st.caption(
    "Phase 1 build — read-only blotter proving the ported pricing engine against the same "
    "10-position seed book as the original HTML tool. Editable cells, column filters/sort, "
    "the P&L heatmap, Delta scenario table, payoff chart, and VaR panel land in Phases 2–3."
)
