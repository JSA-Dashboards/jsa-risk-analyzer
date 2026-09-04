import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jsa_risk.state import init_session_state
from jsa_risk.ui.theme import render_header_and_disclaimer

st.set_page_config(page_title="JSA Risk Analyzer", page_icon="🌽", layout="wide")

init_session_state()
render_header_and_disclaimer()

dashboard_page = st.Page("pages/dashboard.py", title="Risk dashboard", default=True)
add_position_page = st.Page("pages/add_position.py", title="Add position")
import_excel_page = st.Page("pages/import_excel.py", title="Import from Excel")

nav = st.navigation([dashboard_page, add_position_page, import_excel_page])
nav.run()
