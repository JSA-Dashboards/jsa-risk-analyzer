from datetime import date

from jsa_risk.pricing.symbols import (
    SERIAL_TO_QUARTERLY,
    canonical_contract_key,
    contract_display_name,
    decode_contract_symbol,
)


def test_decodes_a_quarterly_future():
    d = decode_contract_symbol("ZCZ26")
    assert d.expiry_month == "Z"
    assert d.year2 == "26"
    assert d.is_serial is False
    assert d.underlying_key == "Z26"


def test_decodes_a_serial_option_to_its_next_quarterly():
    # October (V) is not a real corn futures month — it's a serial option on the December future.
    d = decode_contract_symbol("ZCV26")
    assert d.expiry_month == "V"
    assert d.is_serial is True
    assert d.underlying_month == "Z"
    assert d.underlying_key == "Z26"


def test_every_serial_month_maps_to_the_correct_next_quarterly():
    expected = {"F": "H", "G": "H", "J": "K", "M": "N", "Q": "U", "V": "Z", "X": "Z"}
    assert SERIAL_TO_QUARTERLY == expected
    for serial_letter, quarterly_letter in expected.items():
        d = decode_contract_symbol(f"ZC{serial_letter}27")
        assert d.underlying_month == quarterly_letter
        assert d.underlying_key == quarterly_letter + "27"


def test_rejects_unparseable_or_short_symbols():
    assert decode_contract_symbol("ZC") is None
    assert decode_contract_symbol("") is None
    assert decode_contract_symbol(None) is None
    assert decode_contract_symbol("ZCAB6") is None  # 'A' is not a valid month code


def test_canonical_contract_key_falls_back_to_normalized_raw_label():
    assert canonical_contract_key("ZCZ26") == "Z26"
    assert canonical_contract_key("garbage") == "GARBAGE"
    assert canonical_contract_key(None) == ""


def test_contract_display_name():
    assert contract_display_name("ZCZ26") == "Dec '26"
    assert contract_display_name("ZCV26") == "Dec '26 (via Oct option)"


def test_quarterly_contract_does_not_roll_the_day_before_its_own_month_starts():
    d = decode_contract_symbol("ZCU26", today=date(2026, 8, 31))
    assert d.is_serial is False
    assert d.underlying_key == "U26"


def test_quarterly_contract_rolls_forward_on_the_first_of_its_own_month():
    d = decode_contract_symbol("ZCU26", today=date(2026, 9, 1))
    assert d.is_serial is True
    assert d.underlying_key == "Z26"
    assert d.underlying_month_name == "Dec"


def test_a_serial_option_whose_target_has_since_rolled_cascades_forward_too():
    # An October option nominally targets December -- if December has itself since
    # rolled off (i.e. it's now Dec 1 or later), it should cascade to March next year.
    d = decode_contract_symbol("ZCV26", today=date(2026, 12, 1))
    assert d.underlying_key == "H27"
    assert d.underlying_year2 == "27"


def test_cascades_across_multiple_stale_quarterly_contracts_and_a_year_boundary():
    # As of Mar 15 2027: U26 (Sep '26) is long expired -> rolls to Z26 -> that's also
    # expired (past Dec 1 '26) -> rolls to H27 (Mar '27) -> Mar 1 '27 has also passed,
    # so it keeps going to K27 (May '27), which hasn't started yet.
    d = decode_contract_symbol("ZCU26", today=date(2027, 3, 15))
    assert d.underlying_key == "K27"
    assert d.underlying_month_name == "May"
    assert d.underlying_year2 == "27"


def test_contract_display_name_reflects_a_year_crossing_roll():
    assert contract_display_name("ZCV26", today=date(2026, 12, 1)) == "Mar '27 (via Oct option)"
