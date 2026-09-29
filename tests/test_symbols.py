from datetime import date

from jsa_risk.pricing.commodities import FEEDER_CATTLE, LIVE_CATTLE, SOYBEANS
from jsa_risk.pricing.symbols import (
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


def test_every_corn_serial_month_maps_to_the_correct_next_listed_month():
    expected = {"F": "H", "G": "H", "J": "K", "M": "N", "Q": "U", "V": "Z", "X": "Z"}
    for serial_letter, listed_letter in expected.items():
        d = decode_contract_symbol(f"ZC{serial_letter}27")
        assert d.underlying_month == listed_letter
        assert d.underlying_key == listed_letter + "27"


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


class TestOtherCommodities:
    def test_soybeans_lists_more_months_than_corn(self):
        # Soybeans list a January contract (F) that corn does not.
        d = decode_contract_symbol("ZSF27", today=date(2026, 9, 24), commodity=SOYBEANS)
        assert d.is_serial is False
        assert d.underlying_key == "F27"

    def test_soybeans_december_is_serial_and_rolls_into_next_january(self):
        # Soybeans list no December future at all -- unlike corn, Dec is always serial,
        # and (being after every listed month) rolls into January of *next* year, not
        # December's own year.
        d = decode_contract_symbol("ZSZ26", today=date(2026, 9, 24), commodity=SOYBEANS)
        assert d.is_serial is True
        assert d.underlying_month == "F"
        assert d.underlying_key == "F27"
        assert contract_display_name("ZSZ26", today=date(2026, 9, 24), commodity=SOYBEANS) == "Jan '27 (via Dec option)"

    def test_live_cattle_listed_months_and_roll(self):
        # Live cattle lists Feb/Apr/Jun/Aug/Oct/Dec (G,J,M,Q,V,Z) -- Mar (H) is serial and
        # rolls to Apr (J).
        d = decode_contract_symbol("LEH26", today=date(2026, 1, 1), commodity=LIVE_CATTLE)
        assert d.is_serial is True
        assert d.underlying_key == "J26"

    def test_feeder_cattle_listed_months_and_roll(self):
        # Feeder cattle lists Jan/Mar/Apr/May/Aug/Sep/Oct/Nov (F,H,J,K,Q,U,V,X) -- Feb (G)
        # is serial and rolls to Mar (H).
        d = decode_contract_symbol("GFG26", today=date(2026, 1, 1), commodity=FEEDER_CATTLE)
        assert d.is_serial is True
        assert d.underlying_key == "H26"

    def test_same_raw_key_decodes_differently_per_commodity(self):
        # "H26" (Mar '26) is itself a listed month for corn but not for live cattle --
        # the commodity spec, not the letter alone, decides.
        corn_decoded = decode_contract_symbol("ZCH26", today=date(2026, 1, 1))
        cattle_decoded = decode_contract_symbol("LEH26", today=date(2026, 1, 1), commodity=LIVE_CATTLE)
        assert corn_decoded.is_serial is False
        assert cattle_decoded.is_serial is True
