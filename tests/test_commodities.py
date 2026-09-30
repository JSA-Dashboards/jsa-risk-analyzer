from jsa_risk.pricing.commodities import (
    CORN,
    FEEDER_CATTLE,
    LIVE_CATTLE,
    SOYBEANS,
    get_commodity,
    reference_key,
)


def test_get_commodity_resolves_each_known_code():
    assert get_commodity("ZC") is CORN
    assert get_commodity("ZS") is SOYBEANS
    assert get_commodity("LE") is LIVE_CATTLE
    assert get_commodity("GF") is FEEDER_CATTLE


def test_get_commodity_falls_back_to_corn_for_an_unknown_code():
    assert get_commodity("XX") is CORN
    assert get_commodity("") is CORN


def test_reference_key_prefixes_with_the_commodity_code():
    assert reference_key(CORN, "Z26") == "ZCZ26"
    assert reference_key(SOYBEANS, "F27") == "ZSF27"
    assert reference_key(LIVE_CATTLE, "G26") == "LEG26"
    assert reference_key(FEEDER_CATTLE, "H26") == "GFH26"


def test_all_commodity_codes_are_exactly_two_characters():
    # De-prefixing logic (state.get_contract_marks/get_iv_provenance) slices by
    # len(commodity.code), so every code must be exactly 2 characters.
    for spec in (CORN, SOYBEANS, LIVE_CATTLE, FEEDER_CATTLE):
        assert len(spec.code) == 2


def test_contract_sizes_and_units_are_distinct_by_product_type():
    assert CORN.unit == SOYBEANS.unit == "bu"
    assert LIVE_CATTLE.unit == FEEDER_CATTLE.unit == "lb"
    assert CORN.contract_size == SOYBEANS.contract_size == 5000
    assert LIVE_CATTLE.contract_size == 40000
    assert FEEDER_CATTLE.contract_size == 50000


def test_each_commodity_has_its_own_fallback_price_in_its_own_unit():
    # A shared $4.62 fallback (corn's own, $/bu) fed to a $/lb commodity like cattle makes
    # every option look absurdly deep in- or out-of-the-money against that phantom price --
    # each commodity needs a fallback in its own realistic ballpark, not corn's.
    assert CORN.default_price == 4.62
    for spec in (SOYBEANS, LIVE_CATTLE, FEEDER_CATTLE):
        assert spec.default_price != CORN.default_price
        assert spec.default_price > 0
