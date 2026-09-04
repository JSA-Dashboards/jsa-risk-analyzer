from jsa_risk.importer.mapping import auto_map, match_header_idx


def test_simple_sheet_maps_by_loose_guess():
    headers = ["Symbol", "Type", "Strike", "Expiration", "Lots", "Premium", "Last Tick"]
    mapping = auto_map(headers, remembered=None)
    assert headers[mapping["label"]] == "Symbol"
    assert headers[mapping["type"]] == "Type"
    assert headers[mapping["strike"]] == "Strike"
    assert headers[mapping["expiryDate"]] == "Expiration"
    assert headers[mapping["qty"]] == "Lots"
    assert headers[mapping["entry"]] == "Premium"
    assert headers[mapping["lastTick"]] == "Last Tick"
    assert mapping["iv"] == -1
    assert mapping["positionDir"] == -1


def test_rich_export_prefers_plain_qty_over_outright_or_total_qty():
    headers = ["Position", "Qty", "Outright Qty", "Spread Qty", "Total Qty", "Instrument",
               "Call/Put", "Strike", "Expiration Date", "Price", "Estimated Price", "Last Tick"]
    mapping = auto_map(headers, remembered=None)
    assert headers[mapping["qty"]] == "Qty"
    assert headers[mapping["positionDir"]] == "Position"
    assert headers[mapping["label"]] == "Instrument"
    assert headers[mapping["entry"]] == "Price"


def test_a_saved_preset_wins_over_the_generic_guess():
    headers = ["Weird Col A", "Weird Col B"]
    remembered = {"label": "Weird Col B"}
    mapping = auto_map(headers, remembered=remembered)
    assert headers[mapping["label"]] == "Weird Col B"


def test_match_header_idx_is_case_insensitive_and_exact():
    headers = ["Symbol", "Outright Qty"]
    assert match_header_idx("symbol", headers) == 0
    assert match_header_idx("Qty", headers) == -1  # not an exact match to "Outright Qty"
    assert match_header_idx(None, headers) == -1
