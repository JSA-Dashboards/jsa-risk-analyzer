from datetime import date, timedelta

import pandas as pd
import streamlit as st

from jsa_risk.data import positions_repo, presets_repo, reference_repo
from jsa_risk.importer.commit import positions_from_staging
from jsa_risk.importer.mapping import IMPORT_TARGETS, auto_map, mapping_to_header_names
from jsa_risk.importer.parsing import parse_pasted_text
from jsa_risk.importer.staging import build_staging_row, staging_row_valid
from jsa_risk.pricing.symbols import canonical_contract_key
from jsa_risk.state import refresh_positions

st.markdown("###### Paste or upload a position sheet")
st.caption(
    "Works for corn options and futures in the same sheet — column names and order don't need "
    "to match, you'll map them next. Every row needs a Contract symbol. Strike, entry/premium, "
    "and last-tick prices are all read as cents/bu. If your Qty column is unsigned, also map "
    "Position (\"Net Long\"/\"Net Short\"/\"Net\") to supply the sign — a bare \"Net\" means flat "
    "and won't import. **Importing replaces the whole book.**"
)


def _sample_text() -> str:
    exp1 = (date.today() + timedelta(days=32)).isoformat()
    exp2 = (date.today() + timedelta(days=95)).isoformat()
    return (
        "Symbol\tType\tStrike\tExpiration\tLots\tPremium\tLast Tick\n"
        f"ZCU26\tCall\t500\t{exp1}\t-30\t21\t2.0\n"
        f"ZCU26\tPut\t430\t{exp1}\t30\t19\t\n"
        "ZCU26\t\t\t\t10\t455\t\n"
        f"ZCZ26\tPut\t450\t{exp2}\t20\t22\t\n"
        f"ZCZ26\tCall\t490\t{exp2}\t-20\t15\t\n"
        "ZCZ26\t\t\t\t-8\t480\t465.25\n"
    )


col1, col2 = st.columns([4, 1])
with col2:
    st.write("")
    has_header = st.checkbox("First row is headers", value=True, key="import_has_header")
    load_sample_clicked = st.button("Load sample sheet")
if load_sample_clicked:
    st.session_state.import_paste_text = _sample_text()
with col1:
    pasted = st.text_area("Paste sheet cells here", key="import_paste_text", height=140,
                           placeholder="Symbol\tType\tStrike\tExpiration\tQty\tIV%\tEntry")

c1, c2 = st.columns(2)
parse_clicked = c1.button("Parse data", type="primary")
if c2.button("Reset"):
    for k in ["import_headers", "import_rows", "import_mapping", "import_staging"]:
        st.session_state.pop(k, None)
    st.rerun()

if parse_clicked:
    headers, rows = parse_pasted_text(st.session_state.import_paste_text, has_header)
    st.session_state.import_headers = headers
    st.session_state.import_rows = rows
    remembered = presets_repo.get_default_preset() or presets_repo.get_last_used_mapping()
    st.session_state.import_mapping = auto_map(headers, remembered)
    st.session_state.pop("import_staging", None)
    st.success(f"Parsed {len(rows)} row(s), {len(headers)} column(s). Map the columns below.")

if "import_headers" in st.session_state:
    headers = st.session_state.import_headers
    st.markdown("---")
    st.markdown("###### Map columns")

    presets = presets_repo.list_presets()
    preset_col, save_col = st.columns([2, 2])
    with preset_col:
        chosen_preset = st.selectbox("Load a saved preset", ["— none —"] + list(presets.keys()))
        if chosen_preset != "— none —" and st.button("Apply preset"):
            st.session_state.import_mapping = {
                t.key: headers.index(presets[chosen_preset][t.key]) if presets[chosen_preset].get(t.key) in headers else -1
                for t in IMPORT_TARGETS
            }
            st.rerun()
    with save_col:
        preset_name = st.text_input("Save current mapping as preset named…")
        if st.button("Save preset") and preset_name:
            header_mapping = mapping_to_header_names(st.session_state.import_mapping, headers)
            presets_repo.save_preset(preset_name, header_mapping, created_by="CJACOBS")
            st.success(f'Saved preset "{preset_name}".')
            st.rerun()

    options = ["— none —"] + headers
    new_mapping = {}
    cols = st.columns(3)
    for i, target in enumerate(IMPORT_TARGETS):
        idx = st.session_state.import_mapping.get(target.key, -1)
        with cols[i % 3]:
            selection = st.selectbox(target.label, options, index=idx + 1, key=f"map_{target.key}")
        new_mapping[target.key] = options.index(selection) - 1
    st.session_state.import_mapping = new_mapping

    if st.button("Build preview", type="primary"):
        header_mapping = mapping_to_header_names(new_mapping, headers)
        presets_repo.set_last_used_mapping(header_mapping, updated_by="CJACOBS")
        staging = [build_staging_row(row, headers, new_mapping) for row in st.session_state.import_rows]
        st.session_state.import_staging = staging

if "import_staging" in st.session_state:
    st.markdown("---")
    st.markdown("###### Preview & fix")
    staging = st.session_state.import_staging
    df = pd.DataFrame([{
        "Label": r.label, "Type": r.type, "Strike": r.strike, "Expiry": r.expiry,
        "Qty": r.qty, "IV%": r.iv, "Entry": r.entry, "Last tick": r.last_tick,
        "Status": "Ready" if staging_row_valid(r) else "Fix",
    } for r in staging])
    st.dataframe(df, hide_index=True, use_container_width=True)

    valid_count = sum(1 for r in staging if staging_row_valid(r))
    st.caption(f"{valid_count} of {len(staging)} row(s) are ready to import.")

    if st.button(f"Replace book with {valid_count} position(s)", type="primary", disabled=valid_count == 0):
        positions, estimated_count = positions_from_staging(
            staging,
            get_contract_price=reference_repo.get_contract_price,
            snapshot_iv=reference_repo.snapshot_iv,
            canonical_contract_key=canonical_contract_key,
        )
        header_mapping = mapping_to_header_names(st.session_state.import_mapping, st.session_state.import_headers)
        batch_id = positions_repo.replace_book(
            positions, mapping=header_mapping, source_filename="pasted sheet", imported_by="CJACOBS",
        )
        refresh_positions()
        for k in ["import_headers", "import_rows", "import_mapping", "import_staging"]:
            st.session_state.pop(k, None)
        msg = f"Replaced the book with {len(positions)} position(s) (batch {batch_id})."
        if estimated_count:
            msg += f" {estimated_count} had no IV in the sheet — filled from the market snapshot."
        st.success(msg)
