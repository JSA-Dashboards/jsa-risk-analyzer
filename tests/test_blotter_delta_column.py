"""The per-leg Delta column: the option's own greek, beside the position-scaled one."""
from datetime import date

import pytest

from jsa_risk.pricing.commodities import CORN, LIVE_CATTLE
from jsa_risk.pricing.stress import Position, StressState, eval_position
from jsa_risk.ui.blotter import _columns, _delta_col, _signed_columns, build_blotter_dataframe

F = 2.2935
EXPIRY = date(2027, 2, 5)


def price_book(_key):
    return F


def a_book():
    return [
        Position(id=1, label="LEG27", type="put", qty=-160, entry=0.0351, strike=2.19,
                 expiry_date=EXPIRY, iv=14.0656),
        Position(id=2, label="LEG27", type="call", qty=160, entry=0.0313, strike=2.39,
                 expiry_date=EXPIRY, iv=14.0656),
    ]


def frame(positions, commodity=LIVE_CATTLE):
    return build_blotter_dataframe(positions, StressState(), price_book, commodity=commodity)


def test_delta_times_qty_times_contract_size_reproduces_the_pound_column():
    """The raw greek sits immediately left of the scaled one so a reader can sanity-check
    the sign and rough size of one against the other.

    It will NOT reconcile to the pound, and that is arithmetic rather than a defect: the
    column prints four decimals, so half a tick of rounding is 0.00005 x 160 x 40,000 =
    320 lb on a 160-lot. The bound below is exactly that, and it scales with position
    size -- a 1,000-lot would be out by up to 2,000 lb on a seven-figure number. Printing
    more decimals would tighten it and make the column unreadable; what is NOT acceptable
    is claiming the two audit each other to the pound when they do not."""
    positions = a_book()
    df = frame(positions)
    for p, (_, row) in zip(positions, df.iterrows()):
        implied = row["Delta"] * p.qty * LIVE_CATTLE.contract_size
        bound = 0.5e-4 * abs(p.qty) * LIVE_CATTLE.contract_size
        assert implied == pytest.approx(row["Delta (lb)"], abs=bound + 1)


def test_a_put_keeps_its_own_negative_delta_while_the_position_reads_long():
    """Short 160 puts is LONG delta. The raw column reports the OPTION (-0.29), the scaled
    one the POSITION (+1.88m lb). Flipping the raw sign to match the position would make
    `Delta x Qty` stop reproducing `Delta (lb)` -- the identity above is what decides this,
    not a preference about which sign looks friendlier."""
    put, call = frame(a_book()).itertuples(index=False)
    assert put.Delta < 0 and getattr(put, "_11") > 0      # Delta (lb) is positional here
    assert call.Delta > 0


def test_a_future_is_one_delta():
    df = frame([Position(id=9, label="LEZ26", type="future", qty=3, entry=2.20,
                         underlying_override="Z26")])
    assert df["Delta"].iloc[0] == 1.0
    assert df["Delta (lb)"].iloc[0] == 3 * LIVE_CATTLE.contract_size


def test_a_zero_qty_row_still_has_a_delta():
    """It is carried on PositionEval rather than back-derived from the scaled column --
    `delta_d / (qty * size)` divides by zero the moment somebody edits a Qty to 0, which
    the blotter lets them do."""
    df = frame([Position(id=1, label="LEG27", type="call", qty=0, entry=0.03, strike=2.39,
                         expiry_date=EXPIRY, iv=14.0656)])
    assert 0 < df["Delta"].iloc[0] < 1
    assert df["Delta (lb)"].iloc[0] == 0


def test_delta_sits_immediately_left_of_the_scaled_column():
    cols = _columns(LIVE_CATTLE)
    assert cols[cols.index("Delta") + 1] == _delta_col(LIVE_CATTLE)
    assert cols[cols.index("Delta") - 1] == "Mark"


def test_the_raw_delta_is_not_sign_colored():
    """Green/red here means gain, or long exposure. A put's -0.29 is neither -- short 160
    of it is long 1.88m lb -- so coloring it would put a red number and a green one on one
    row describing one leg."""
    assert "Delta" not in _signed_columns(LIVE_CATTLE)
    assert _delta_col(LIVE_CATTLE) in _signed_columns(LIVE_CATTLE)


def test_the_two_delta_columns_are_distinguishable_for_grains_too():
    """`Delta` and `Delta (bu)` must not collide into one name -- a DataFrame silently
    keeps both under a duplicated label and the column_config then addresses only one."""
    cols = _columns(CORN)
    assert _delta_col(CORN) == "Delta (bu)"
    assert len(cols) == len(set(cols))
