from datetime import date

import pytest

from jsa_risk.pricing.commodities import LIVE_CATTLE
from jsa_risk.pricing.stress import (
    Position,
    StressState,
    effective_underlying_display,
    effective_underlying_key,
    eval_position,
)

TODAY = date(2026, 1, 1)


def price_book(label):
    prices = {"Z26": 5.00, "U26": 5.15}
    return prices[label]


def make_future(qty=10, entry=4.80, last_tick=None, import_mark=None):
    return Position(
        id=1, label="ZCZ26", type="future", qty=qty, entry=entry,
        last_tick=last_tick, import_mark=import_mark,
    )


def make_option(qty=-10, strike=5.00, iv=25.0, entry=0.20, last_tick=None, import_mark=None, is_call=True):
    return Position(
        id=2, label="ZCZ26", type="call" if is_call else "put", qty=qty, entry=entry,
        strike=strike, expiry_date=date(2026, 4, 1), iv=iv,
        last_tick=last_tick, import_mark=import_mark,
    )


class TestFutures:
    def test_no_stress_no_tick_uses_the_contract_mark(self):
        p = make_future()
        r = eval_position(p, StressState(), price_book, today=TODAY)
        assert r.price == 5.00
        assert r.delta_d == 10 * 5000
        assert r.gamma_d == 0 and r.vega_d == 0 and r.theta_d == 0
        assert r.pnl == pytest.approx((5.00 - 4.80) * 10 * 5000)

    def test_no_stress_with_tick_uses_the_tick(self):
        p = make_future(last_tick=4.90)
        r = eval_position(p, StressState(), price_book, today=TODAY)
        assert r.price == 4.90
        assert r.model_price == 5.00

    def test_stress_engaged_ignores_the_tick(self):
        p = make_future(last_tick=4.90)
        stress = StressState(price_pct=10)  # +10% price shock
        r = eval_position(p, stress, price_book, today=TODAY)
        assert r.price == pytest.approx(5.50)  # stressed model price, NOT the 4.90 tick
        assert r.model_price == pytest.approx(5.50)

    def test_hypothetical_F_override_ignores_the_tick_even_with_no_stress(self):
        """This is exactly what the heatmap/delta-scenario/payoff panels rely on."""
        p = make_future(last_tick=4.90)
        r = eval_position(p, StressState(), price_book, F_override=6.00, today=TODAY)
        assert r.price == 6.00

    def test_import_gain_uses_import_mark_not_entry(self):
        p = make_future(entry=4.80, last_tick=4.90, import_mark=4.70)
        r = eval_position(p, StressState(), price_book, today=TODAY)
        assert r.pnl == pytest.approx((4.90 - 4.80) * 10 * 5000)
        assert r.import_gain == pytest.approx((4.90 - 4.70) * 10 * 5000)
        assert r.pnl != r.import_gain

    def test_import_gain_falls_back_to_entry_when_never_set(self):
        p = make_future(entry=4.80, last_tick=4.90, import_mark=None)
        r = eval_position(p, StressState(), price_book, today=TODAY)
        assert r.import_gain == r.pnl


class TestOptions:
    def test_short_call_has_negative_delta_exposure(self):
        p = make_option(qty=-10, is_call=True)
        r = eval_position(p, StressState(), price_book, today=TODAY)
        assert r.delta_d < 0  # short a call -> negative dollar delta

    def test_days_forward_stress_shrinks_time_to_expiry(self):
        p = make_option(qty=10)
        near_expiry_stress = StressState(days=89)  # position expires in 90 days from TODAY
        r = eval_position(p, near_expiry_stress, price_book, today=TODAY)
        # 1 day of time value left should price close to (but not exactly) intrinsic.
        intrinsic = max(price_book("Z26") - p.strike, 0) if p.type == "call" else max(p.strike - price_book("Z26"), 0)
        assert r.model_price == pytest.approx(intrinsic, abs=0.05)

    def test_stress_engaged_ignores_the_tick_for_options_too(self):
        p = make_option(last_tick=0.05)
        stress = StressState(vol_pct=50)
        r = eval_position(p, stress, price_book, today=TODAY)
        assert r.price != 0.05
        assert r.price == r.model_price


class TestEffectiveUnderlying:
    def test_no_override_falls_back_to_the_auto_derived_key_from_the_label(self):
        p = make_future()  # label="ZCZ26", no override
        assert effective_underlying_key(p, today=TODAY) == "Z26"

    def test_override_takes_precedence_over_the_label_entirely(self):
        p = Position(id=3, label="ZCZ26", type="future", qty=1, entry=5.0, underlying_override="u26")
        assert effective_underlying_key(p, today=TODAY) == "U26"

    def test_override_is_used_for_pricing_not_just_display(self):
        p = Position(
            id=4, label="ZCZ26", type="future", qty=10, entry=5.10, underlying_override="U26",
        )
        r = eval_position(p, StressState(), price_book, today=TODAY)
        assert r.price == price_book("U26")

    def test_display_without_override_matches_contract_display_name(self):
        p = make_future()
        assert effective_underlying_display(p, today=TODAY) == "Dec '26"

    def test_display_with_override_is_tagged(self):
        p = Position(id=5, label="ZCZ26", type="future", qty=1, entry=5.0, underlying_override="U26")
        assert effective_underlying_display(p, today=TODAY) == "Sep '26 (override)"

    def test_contract_size_scales_with_the_selected_commodity(self):
        # Same position, same futures mark -- only the commodity's $ multiplier differs
        # (corn: 5000 bu/contract vs. live cattle: 40000 lb/contract). Z26 decodes the
        # same way under both specs since December is a listed month for each.
        p = make_future(qty=10, entry=4.80)
        r_corn = eval_position(p, StressState(), price_book, today=TODAY)
        r_cattle = eval_position(p, StressState(), price_book, today=TODAY, commodity=LIVE_CATTLE)
        assert r_cattle.delta_d == pytest.approx(r_corn.delta_d * (LIVE_CATTLE.contract_size / 5000))

    def test_display_with_override_does_not_re_roll_even_after_that_contract_expired(self):
        # If the override itself names a contract whose own month has since begun, the
        # display must still say exactly what it's pricing against -- not silently roll
        # it forward again, which would misrepresent what underlying_override actually
        # pins pricing to (see effective_underlying_key: it's used literally).
        today_after_sep_roll = date(2026, 9, 24)
        p = Position(id=6, label="ZCZ26", type="future", qty=1, entry=5.0, underlying_override="U26")
        assert effective_underlying_display(p, today=today_after_sep_roll) == "Sep '26 (override)"
        assert effective_underlying_key(p, today=today_after_sep_roll) == "U26"


class TestCommodityAwareDefaultPrice:
    """Regression test for a real bug: before CommoditySpec.default_price existed, every
    commodity's "no reference data yet" fallback was corn's own $4.62 (a $/bu figure).
    Fed to a $/lb commodity like live cattle, real strikes (~$2/lb) looked wildly
    out-of-the-money against that phantom ~$4.62 "future" -- puts priced with ~0 delta,
    looking like they'd silently dropped out of the book, when they just hadn't been
    given a realistic underlying price yet."""

    def test_deep_otm_distortion_when_fed_the_wrong_commoditys_default_price(self):
        wrong_default_price = 4.62  # corn's $/bu default, fed to a cattle position
        p = Position(
            id=1, label="LEG27", type="put", qty=-1, entry=0.03,
            strike=2.06, expiry_date=date(2026, 6, 1), iv=21.0,
        )
        r = eval_position(p, StressState(), lambda _: wrong_default_price, today=TODAY, commodity=LIVE_CATTLE)
        assert abs(r.delta_d) < 1.0  # the exact symptom reported: delta rounds to 0

    def test_realistic_default_price_avoids_the_distortion(self):
        p = Position(
            id=1, label="LEG27", type="put", qty=-1, entry=0.03,
            strike=2.06, expiry_date=date(2026, 6, 1), iv=21.0,
        )
        r = eval_position(p, StressState(), lambda _: LIVE_CATTLE.default_price, today=TODAY, commodity=LIVE_CATTLE)
        assert abs(r.delta_d) > 1000  # a real, priceable put delta, not a rounding-to-zero sliver
