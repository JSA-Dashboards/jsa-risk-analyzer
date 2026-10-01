import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jsa_risk.auth import require_password
from jsa_risk.pricing.commodities import COMMODITIES
from jsa_risk.state import get_commodity_spec, init_session_state, set_commodity
from jsa_risk.ui.theme import render_header_and_disclaimer

st.set_page_config(page_title="JSA Risk Analyzer", page_icon="📈", layout="wide")

# Hide the Streamlit Community Cloud viewer badge (the profile avatar that links
# to the creator's other apps) for a clean, client-facing footer.
st.markdown(
    "<style>[class*='_profileContainer_']{display:none !important;}</style>",
    unsafe_allow_html=True,
)

require_password()

init_session_state()

def _on_sidebar_commodity_change() -> None:
    set_commodity(st.session_state["commodity_selector"])


with st.sidebar:
    codes = list(COMMODITIES.keys())
    st.selectbox(
        "Commodity",
        codes,
        index=codes.index(get_commodity_spec().code),
        format_func=lambda c: f"{COMMODITIES[c].icon} {COMMODITIES[c].name} ({c})",
        key="commodity_selector",
        on_change=_on_sidebar_commodity_change,
        help="The dashboard prices one commodity at a time — switching starts a fresh book.",
    )

commodity = get_commodity_spec()
render_header_and_disclaimer(commodity.name)

dashboard_page = st.Page("pages/dashboard.py", title="Risk dashboard", default=True)
add_position_page = st.Page("pages/add_position.py", title="Add position")
import_excel_page = st.Page("pages/import_excel.py", title="Import from Excel")

nav = st.navigation([dashboard_page, add_position_page, import_excel_page])
nav.run()
