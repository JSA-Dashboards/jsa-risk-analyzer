import streamlit as st

from jsa_risk.state import get_contract_price, visible_positions
from jsa_risk.ui.blotter import render_editable_blotter, render_import_gain_summary
from jsa_risk.ui.charts import (
    render_delta_scenario,
    render_greeks_bars,
    render_payoff_chart,
    render_pnl_heatmap,
)
from jsa_risk.ui.kpi import render_kpi_strip, render_var_panel
from jsa_risk.ui.market_strip import render_market_strip, render_massive_refresh

flash = st.session_state.pop("_flash_added", None)
if flash:
    st.success(flash)

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

st.markdown("###### Live market data")
render_massive_refresh(positions)
render_market_strip(positions)

st.markdown("---")

st.markdown("###### Position blotter")
st.caption("This book is private to your browser session — Qty and Entry are editable; check Delete to remove a row.")
render_import_gain_summary(positions, stress, get_contract_price)
st.write("")
render_editable_blotter(positions, stress, get_contract_price)

st.markdown("---")
st.markdown("###### Greeks by contract")
render_greeks_bars(positions, stress, get_contract_price)

st.markdown("---")
st.markdown("###### P&L scenario heatmap")
st.caption("Price shock (x-axis, ¢) vs. vol shock (y-axis, %) layered on top of the current stress scenario.")
render_pnl_heatmap(positions, stress, get_contract_price)

st.markdown("###### Delta scenario")
render_delta_scenario(positions, stress, get_contract_price)

st.markdown("---")
st.markdown("###### Portfolio payoff")
st.caption("P&L vs. a corn futures price shock, current vol & time.")
render_payoff_chart(positions, stress, get_contract_price)

st.markdown("---")
st.markdown("###### Value at risk")
render_var_panel(positions, stress, get_contract_price)
