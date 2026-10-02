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
# The Streamlit Cloud badge (creator avatar + logo) is drawn by Cloud's outer page,
# outside this iframe, so CSS here can't reach it; add the rule to the parent
# document instead (same-origin). No-op when run locally.
_BADGE_JS = """<script>(function(){try{var w=window;while(w.parent&&w.parent!==w){try{void w.parent.document;w=w.parent;}catch(e){break;}}var d=w.document;if(d.getElementById('jsa-hide-cloud-badge'))return;var s=d.createElement('style');s.id='jsa-hide-cloud-badge';s.textContent="[class*='_profileContainer_'],[class*='_viewerBadge_']{display:none !important;}";d.head.appendChild(s);}catch(e){}})();</script>"""
try:
    st.html(_BADGE_JS, unsafe_allow_javascript=True)
except TypeError:  # older Streamlit without st.html JS support
    import streamlit.components.v1 as _stc
    _stc.html(_BADGE_JS, height=0)

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
