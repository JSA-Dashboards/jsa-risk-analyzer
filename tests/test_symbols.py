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
