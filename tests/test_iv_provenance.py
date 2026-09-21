"""Staleness rules for the dashboard's implied-vol provenance line."""
from datetime import datetime

from jsa_risk.ui.market_strip import summarize_iv_provenance

NOW = datetime(2026, 9, 21, 8, 0)
DATAMINE = "CME DataMine EOD Preliminary ATM C+P (K=530 @ 2026-09-18)"


def _row(key, as_of, source=DATAMINE, iv=21.0):
    return {"key": key, "iv": iv, "as_of": as_of, "source": source}


def test_caption_names_the_source_without_the_per_contract_detail():
    rows = [_row("Z26", datetime(2026, 9, 18)), _row("H27", datetime(2026, 9, 18))]
    s = summarize_iv_provenance(rows, {"Z26"}, NOW)
    assert "CME DataMine EOD Preliminary" in s["caption"]
    assert "K=530" not in s["caption"]          # strike belongs on the row, not the header
    assert "2026-09-18" in s["caption"] and "2 contract(s)" in s["caption"]


def test_fresh_vols_raise_no_warning():
    rows = [_row("Z26", datetime(2026, 9, 18))]
    assert summarize_iv_provenance(rows, {"Z26"}, NOW)["warning"] is None


def test_vols_older_than_a_long_weekend_warn():
    rows = [_row("Z26", datetime(2026, 9, 10))]
    s = summarize_iv_provenance(rows, {"Z26"}, NOW)
    assert s["warning"] and "11 days old" in s["warning"]
    assert "refresh_iv_from_cme" in s["warning"]


def test_one_lagging_contract_in_the_book_is_called_out():
    rows = [
        _row("Z26", datetime(2026, 9, 18)),
        _row("U26", datetime(2026, 9, 1), source="Barchart corn options quotes"),
    ]
    s = summarize_iv_provenance(rows, {"Z26", "U26"}, NOW)
    assert s["warning"] is None                 # the book as a whole is current
    assert s["behind"] == ["U26"]


def test_a_lagging_contract_not_in_the_book_is_not_nagged_about():
    rows = [
        _row("Z26", datetime(2026, 9, 18)),
        _row("U26", datetime(2026, 9, 1), source="Barchart corn options quotes"),
    ]
    assert summarize_iv_provenance(rows, {"Z26"}, NOW)["behind"] == []


def test_row_with_no_as_of_counts_as_lagging():
    rows = [_row("Z26", datetime(2026, 9, 18)), _row("H27", None)]
    assert summarize_iv_provenance(rows, {"Z26", "H27"}, NOW)["behind"] == ["H27"]


def test_empty_snapshot_produces_nothing_to_show():
    s = summarize_iv_provenance([], {"Z26"}, NOW)
    assert s == {"caption": None, "warning": None, "behind": []}
