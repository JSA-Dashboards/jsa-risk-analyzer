"""The dashboard carries two P&L grids off one computation: `change from here`, re-centred
on the current scenario, and `total since entry`, which is not.

Every cell is the blotter's mark plus the model's change for that shock, so the UNCENTRED
grid's zero cell is the blotter's P&L even when positions carry imported ticks. (It used to
be a pure model valuation, which sat a long way from the tick-marked column.) The CENTRED
grid is unaffected: the tick/model difference is a constant in every cell and cancels.
"""
from datetime import date
from unittest.mock import patch

import pytest

from jsa_risk.pricing.commodities import LIVE_CATTLE
from jsa_risk.pricing.portfolio import portfolio_pnl_at
from jsa_risk.pricing.stress import Position, StressState, eval_position
from jsa_risk.ui import charts

TODAY = date(2026, 1, 1)
NEUTRAL = StressState()
FEB = date(2026, 4, 25)
SHOCKS = [-1.0, -0.5, 0.0, 0.5, 1.0]


def price_book(label):
    return {"G27": 2.288}[label]


def a_call(last_tick=None):
    return Position(
        id=1, label="LEG27", type="call", qty=250, entry=0.0313,
        strike=2.39, expiry_date=FEB, iv=14.3784, last_tick=last_tick,
    )


def grid(positions, centred):
    """The row the renderer builds, with and without re-centring."""
    raw = [portfolio_pnl_at(positions, price_book, NEUTRAL, ps, 0, 0, TODAY, LIVE_CATTLE)
           for ps in SHOCKS]
    centre = raw[SHOCKS.index(0.0)]
    return [v - centre for v in raw] if centred else raw


def blotter_total(positions):
    return sum(eval_position(p, NEUTRAL, price_book, today=TODAY, commodity=LIVE_CATTLE).pnl
               for p in positions)


def test_the_centred_grid_reads_zero_at_the_centre():
    assert grid([a_call(last_tick=0.0260)], centred=True)[SHOCKS.index(0.0)] == 0


def test_the_centred_grid_is_identical_whether_or_not_a_tick_is_loaded():
    """The whole reason this view needs no basis caveat: the tick/model difference is one
    constant across the grid, so it vanishes in the subtraction."""
    assert grid([a_call(last_tick=0.0260)], centred=True) == pytest.approx(
        grid([a_call()], centred=True)
    )


def test_re_centring_does_not_change_the_shape():
    """Only where the surface sits changes -- never the risk."""
    raw, centred = grid([a_call()], False), grid([a_call()], True)
    assert [b - a for a, b in zip(raw, raw[1:])] == pytest.approx(
        [b - a for a, b in zip(centred, centred[1:])]
    )


def test_the_uncentred_grid_centre_is_the_blotters_total():
    """The 0% / 0-vol cell and the blotter's P&L are one number -- a tick-marked book
    included. Each scenario is the blotter's mark plus the model's change, so the model/tick
    gap that used to separate them is carried through rather than left to open up."""
    book = [a_call(last_tick=0.0260)]
    assert grid(book, centred=False)[SHOCKS.index(0.0)] == pytest.approx(blotter_total(book))


def test_the_centre_still_matches_when_the_book_has_no_ticks_or_a_mix():
    for book in ([a_call()], [a_call(last_tick=0.0260), a_call()]):
        assert grid(book, centred=False)[SHOCKS.index(0.0)] == pytest.approx(blotter_total(book))


def captions_for(positions, centred):
    centre = grid(positions, centred=False)[SHOCKS.index(0.0)]
    with patch.object(charts.st, "caption") as cap:
        charts._caption_basis(centre, positions, NEUTRAL, price_book, TODAY, LIVE_CATTLE, centred)
    return [c.args[0] for c in cap.call_args_list]


def test_the_centred_caption_says_the_centre_is_zero_and_claims_no_basis():
    said = captions_for([a_call(last_tick=0.0260)], centred=True)[0]
    assert "reads zero" in said and "cancels out" in said
    assert "blotter" not in said, "nothing to reconcile on this view"


def test_the_uncentred_caption_says_the_centre_is_the_blotter_and_names_the_model():
    said = captions_for([a_call(last_tick=0.0260)], centred=False)[0]
    assert "same total as the position blotter" in said
    assert "Black-76" in said and "American" in said


def test_the_caption_has_no_bare_dollar_amounts():
    r"""Two bare `$` in one markdown block open an inline maths span; the caption quotes no
    amounts at all now, which keeps it out of that trap."""
    said = captions_for([a_call(last_tick=0.0260)], centred=False)[0]
    assert said.count("$") == said.count(r"\$")
