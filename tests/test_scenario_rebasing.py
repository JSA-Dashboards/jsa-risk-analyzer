"""The scenario surfaces are re-based onto the blotter's mark, so the number a reader takes
for "where I stand right now" is the same on all of them.

`portfolio_pnl_at` always reprices off Black-76; the blotter at zero stress prefers an
imported `last_tick`. Before `mark_offset` the heatmap's outlined 0/0 cell and the payoff
chart's Today curve were model valuations disagreeing with the P&L column above them --
on a live cattle book, -$200,500 against -$52,320, with nothing on either surface saying so.
"""
from datetime import date
from unittest.mock import patch

import pytest

from jsa_risk.pricing.commodities import LIVE_CATTLE
from jsa_risk.pricing.portfolio import mark_offset, portfolio_pnl_at
from jsa_risk.pricing.stress import Position, StressState, eval_position
from jsa_risk.ui import charts

TODAY = date(2026, 1, 1)
NEUTRAL = StressState()
FEB = date(2026, 4, 25)


def price_book(label):
    return {"G27": 2.288}[label]


def a_call(last_tick=None):
    return Position(
        id=1, label="LEG27", type="call", qty=250, entry=0.0313,
        strike=2.39, expiry_date=FEB, iv=14.3784, last_tick=last_tick,
    )


def blotter_total(positions, stress=NEUTRAL):
    """Exactly what the blotter's P&L column sums to."""
    return sum(
        eval_position(p, stress, price_book, today=TODAY, commodity=LIVE_CATTLE).pnl
        for p in positions
    )


def cell(positions, price_shock=0.0, vol_shock=0.0, days=0, stress=NEUTRAL):
    """One re-based scenario value, as the renderers build it."""
    base = portfolio_pnl_at(
        positions, price_book, stress, price_shock, vol_shock, days, TODAY, LIVE_CATTLE,
    )
    return base + mark_offset(positions, price_book, stress, TODAY, LIVE_CATTLE)


def test_the_zero_cell_now_equals_the_blotter():
    """The whole point. A tick 20% away from the model price must not split the two."""
    book = [a_call(last_tick=0.0260)]
    assert blotter_total(book) != pytest.approx(
        portfolio_pnl_at(book, price_book, NEUTRAL, 0, 0, 0, TODAY, LIVE_CATTLE)
    ), "fixture must actually exercise a tick/model gap, or this proves nothing"
    assert cell(book) == pytest.approx(blotter_total(book))


def test_the_offset_shifts_the_grid_without_changing_its_shape():
    """Re-basing must not touch the risk -- only where the surface sits."""
    book = [a_call(last_tick=0.0260)]
    shocks = [-2.0, -1.0, 0.0, 1.0, 2.0]
    rebased = [cell(book, ps) for ps in shocks]
    raw = [portfolio_pnl_at(book, price_book, NEUTRAL, ps, 0, 0, TODAY, LIVE_CATTLE) for ps in shocks]
    gaps_rebased = [b - a for a, b in zip(rebased, rebased[1:])]
    gaps_raw = [b - a for a, b in zip(raw, raw[1:])]
    assert gaps_rebased == pytest.approx(gaps_raw)


def test_no_tick_means_no_offset():
    assert mark_offset([a_call()], price_book, NEUTRAL, TODAY, LIVE_CATTLE) == pytest.approx(0.0)


def test_a_stress_scenario_means_no_offset():
    """Under stress `eval_position` drops the tick too, so both sides already agree."""
    book = [a_call(last_tick=0.0260)]
    stressed = StressState(price_pct=5.0)
    assert mark_offset(book, price_book, stressed, TODAY, LIVE_CATTLE) == pytest.approx(0.0)


def test_an_expiry_horizon_does_not_carry_the_offset():
    """At expiry an option is worth its intrinsic value exactly -- there is no quoted-vs-model
    gap left to carry, and shifting the curve would assert the mispricing outlives the option."""
    book = [a_call(last_tick=0.0260)]
    dte = (FEB - TODAY).days
    at_expiry = portfolio_pnl_at(book, price_book, NEUTRAL, 0, 0, dte, TODAY, LIVE_CATTLE)
    # Deep OTM at expiry: the whole premium is lost, offset or not.
    assert at_expiry == pytest.approx(-0.0313 * 250 * LIVE_CATTLE.contract_size)
    assert at_expiry != pytest.approx(at_expiry + mark_offset(book, price_book, NEUTRAL, TODAY, LIVE_CATTLE))


def captions_for(offset):
    with patch.object(charts.st, "caption") as cap:
        charts._caption_basis(offset, LIVE_CATTLE)
    return [c.args[0] for c in cap.call_args_list]


def test_the_caption_always_says_the_cell_matches_the_blotter():
    for offset in (0.0, -148_180.0):
        said = captions_for(offset)[0]
        assert "matching the blotter" in said
        assert "Black-76" in said, "the MOVE away from it is still modelled, and must say so"


def test_the_caption_quotes_the_offset_only_when_there_is_one():
    assert charts._money_md(-148_180.0) in captions_for(-148_180.0)[0]
    assert "tick" not in captions_for(0.0)[0], "no tick in play, nothing to warn about"


def test_the_amount_is_escaped_against_streamlit_latex():
    r"""Two bare `$` in one markdown block open an inline maths span: the signs vanish and
    the text between them is italicised. Shipped exactly that way once and was visible only
    in a browser -- `get_page_text` reads the amounts correctly either way."""
    said = captions_for(-148_180.0)[0]
    assert said.count("$") == said.count(r"\$")
