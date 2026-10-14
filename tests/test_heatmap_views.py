"""The dashboard carries two P&L grids off one computation: `change from here`, re-centred
on the current scenario, and `total since entry`, which is not.

Both are Black-76 throughout -- a shocked scenario cannot be marked to a frozen tick. That
makes the UNCENTRED grid's zero cell a model valuation, which can sit a long way from the
blotter's tick-marked P&L column (-$52,320 against -$200,500 on a live cattle book). Both
are defensible, so the caption reconciles them rather than leaving a reader to meet the
disagreement alone. The CENTRED grid needs none of that: the difference is a constant in
every cell and cancels.
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


def test_the_uncentred_grid_still_disagrees_with_the_blotter_and_that_is_by_design():
    """Reverted a change that bent the grid onto the blotter's mark; it is pure model now,
    and the caption is what closes the gap. If this ever starts matching, the grid has
    quietly acquired a tick and the caption below is no longer doing its job."""
    book = [a_call(last_tick=0.0260)]
    assert grid(book, centred=False)[SHOCKS.index(0.0)] != pytest.approx(blotter_total(book))


def captions_for(positions, centred):
    centre = grid(positions, centred=False)[SHOCKS.index(0.0)]
    with patch.object(charts.st, "caption") as cap:
        charts._caption_basis(centre, positions, NEUTRAL, price_book, TODAY, LIVE_CATTLE, centred)
    return [c.args[0] for c in cap.call_args_list]


def test_the_centred_caption_says_the_centre_is_zero_and_claims_no_basis():
    said = captions_for([a_call(last_tick=0.0260)], centred=True)[0]
    assert "reads zero" in said and "cancels out" in said
    assert "blotter" not in said, "nothing to reconcile on this view"


def test_the_uncentred_caption_names_the_model_and_quotes_both_totals():
    book = [a_call(last_tick=0.0260)]
    said = captions_for(book, centred=False)[0]
    assert "Black-76" in said
    assert charts._money_md(blotter_total(book)) in said, "the blotter's total"
    assert charts._money_md(grid(book, False)[SHOCKS.index(0.0)]) in said, "and the cell's"


def test_no_tick_means_the_caption_drops_the_reconciliation():
    said = captions_for([a_call()], centred=False)[0]
    assert "Black-76" in said and "blotter" not in said


def test_both_amounts_are_escaped_against_streamlit_latex():
    r"""Two bare `$` in one markdown block open an inline maths span: the signs vanish and
    the text between them is italicised. Shipped that way once; visible only in a browser,
    since `get_page_text` reads the amounts correctly either way."""
    said = captions_for([a_call(last_tick=0.0260)], centred=False)[0]
    assert said.count("$") == said.count(r"\$")
