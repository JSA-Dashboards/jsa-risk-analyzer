from jsa_risk.importer.mapping import auto_map
from jsa_risk.importer.staging import (
    build_staging_row,
    looks_like_unit_mismatch,
    parse_num,
    staging_row_valid,
    strip_label_suffix,
)

HEADERS = ["Position", "Qty", "Instrument", "Call/Put", "Strike", "Expiration Date", "Price", "Last Tick"]
MAPPING = auto_map(HEADERS, remembered=None)


def row(position, qty, instrument, call_put="", strike="", expiry="", price="", last_tick=""):
    return build_staging_row([position, qty, instrument, call_put, strike, expiry, price, last_tick], HEADERS, MAPPING)


def test_short_position_negates_the_unsigned_qty():
    r = row("Net Short", "7", "ZCZ26")
    assert r.qty == -7


def test_long_position_keeps_the_unsigned_qty_positive():
    r = row("Net Long", "7", "ZCZ27")
    assert r.qty == 7


def test_bare_net_with_no_direction_forces_qty_to_zero_and_is_dropped():
    r = row("Net", "0", "ZCV26{A}P525", "Put", "525", "09/25/2026")
    assert r.qty == 0
    assert staging_row_valid(r) is False


def test_unmapped_position_column_uses_qty_as_already_signed():
    headers = ["Symbol", "Type", "Strike", "Expiration", "Lots", "Premium"]
    mapping = auto_map(headers, remembered=None)
    r = build_staging_row(["ZCZ26", "Call", "500", "9/18/2026", "-20", "0.21"], headers, mapping)
    assert r.qty == -20


def test_symbol_suffix_is_stripped_before_decoding():
    r = row("Net Short", "6", "ZCZ27{A}C550", "Call", "550", "11/26/2027")
    assert r.label == "ZCZ27"
    assert strip_label_suffix("ZCZ27{A}C550") == "ZCZ27"
    assert strip_label_suffix("ZCZ26") == "ZCZ26"


def test_strike_and_entry_and_last_tick_convert_cents_to_dollars():
    r = row("Net Short", "6", "ZCZ27{A}C550", "Call", "550", "11/26/2027", "23.", "42.25")
    assert r.strike == 5.50
    assert r.entry == 0.23
    assert r.last_tick == 0.4225


def test_no_strike_means_a_futures_position():
    r = row("Net Short", "8", "ZCZ26", "", "", "", "480.0")
    assert r.type == "future"
    assert r.strike is None
    assert r.entry == 4.80


def test_parse_num_handles_parens_negative_and_commas():
    assert parse_num("1,234.50") == 1234.50
    assert parse_num("($5,775.00)") == -5775.00
    assert parse_num("") is None
    assert parse_num(None) is None


def test_unit_mismatch_heuristic():
    assert looks_like_unit_mismatch(440, 4.62) is True  # 440 vs 4.62 ref -> looks like cents left unconverted
    assert looks_like_unit_mismatch(4.70, 4.62) is False
    assert looks_like_unit_mismatch(None, 4.62) is False
