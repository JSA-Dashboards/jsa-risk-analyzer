"""The heatmap's outlined 0/0 cell is a MODEL valuation; the blotter's P&L column is not,
wherever a last tick was imported. Both are defensible, so the chart has to say which it is
and reconcile itself against the table above it -- see `_caption_model_basis`.
"""
from datetime import date
from unittest.mock import patch

from jsa_risk.pricing.commodities import LIVE_CATTLE
from jsa_risk.pricing.portfolio import portfolio_pnl_at
from jsa_risk.pricing.stress import Position, StressState
from jsa_risk.ui import charts

TODAY = date(2026, 1, 1)
NEUTRAL = StressState()


def price_book(label):
    return {"G27": 2.288}[label]


def a_call(last_tick=None):
    return Position(
        id=1, label="LEG27", type="call", qty=250, entry=0.0313,
        strike=2.39, expiry_date=date(2026, 4, 25), iv=14.3784, last_tick=last_tick,
    )


def base_cell(positions, stress=NEUTRAL):
    """Exactly what the renderer puts in the outlined cell: zero price shock, zero vol
    shock, on top of the current scenario."""
    return portfolio_pnl_at(positions, price_book, stress, 0, 0, 0, TODAY, LIVE_CATTLE)


def captions_for(positions, stress=NEUTRAL):
    with patch.object(charts.st, "caption") as cap:
        charts._caption_model_basis(
            base_cell(positions, stress), positions, stress, price_book, TODAY, LIVE_CATTLE,
        )
    return [c.args[0] for c in cap.call_args_list]


def test_the_cell_is_always_named_as_model_priced():
    said = captions_for([a_call()])[0]
    assert "model" in said.lower() and "Black-76" in said


def test_a_loaded_tick_makes_the_blotter_disagree_and_the_gap_is_printed():
    """A tick well below the model price: the two surfaces must not both stay silent."""
    book = [a_call(last_tick=0.0260)]
    said = captions_for(book)
    assert len(said) == 2, "a divergence must be reported, not left to be discovered"
    assert charts._money_md(base_cell(book)) in said[1], "the cell's own figure"
    tick_pnl = (0.0260 - 0.0313) * 250 * LIVE_CATTLE.contract_size
    assert charts._money_md(tick_pnl) in said[1], "beside the blotter's total"


def test_the_two_amounts_are_escaped_against_streamlit_latex():
    r"""Two bare `$` in one markdown block open an inline maths span: the signs vanish
    and the text between them is italicised. Shipped exactly that way and was only
    visible in a browser -- `get_page_text` reads the amounts correctly either way."""
    said = captions_for([a_call(last_tick=0.0260)])[1]
    assert said.count("$") == said.count(r"\$"), "every $ in the sentence must be escaped"


def test_no_tick_means_no_second_caption():
    """Model and blotter agree exactly here; a reconciliation nobody needs is noise."""
    assert len(captions_for([a_call()])) == 1


def test_a_stress_scenario_also_silences_it():
    """Under stress the blotter drops the tick too, so there is nothing to reconcile."""
    assert len(captions_for([a_call(last_tick=0.0260)], StressState(price_pct=5.0))) == 1
