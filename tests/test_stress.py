from datetime import date

import pytest

from jsa_risk.pricing.stress import Position, StressState, eval_position

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
