"""Mark is editable, and the edit goes into `last_tick` -- the field the automatic mark
already prefers, so nothing about how a mark populates changes.

The three things worth pinning: a typed mark reaches the position and shows up in the
grid; a CLEARED cell goes back to the model rather than writing a zero; and the column is
locked under a stress scenario, where `eval_position` ignores a tick entirely and an edit
would be stored and never displayed.
"""
import ast
import inspect
from datetime import date, timedelta
from pathlib import Path

import pytest

from jsa_risk.pricing.commodities import LIVE_CATTLE
from jsa_risk.pricing.stress import Position, StressState, eval_position
from jsa_risk.ui import blotter

TODAY = date.today()
NEUTRAL = StressState()
SHOCKED = StressState(price_pct=5.0)


def price_book(label):
    return {"G27": 2.288}[label]


def a_call(last_tick=None):
    return Position(
        id=1, label="LEG27", type="call", qty=250, entry=0.0313, strike=2.39,
        expiry_date=TODAY + timedelta(days=114), iv=14.3784, last_tick=last_tick,
    )


def mark_of(position, stress=NEUTRAL):
    df = blotter.build_blotter_dataframe([position], stress, price_book, LIVE_CATTLE)
    return df.iloc[0]["Mark"]


def test_a_typed_mark_is_what_the_grid_then_shows():
    """The point of the feature."""
    model = mark_of(a_call())
    typed = mark_of(a_call(last_tick=0.0260))
    assert typed == pytest.approx(0.0260)
    assert typed != pytest.approx(model), "fixture must differ from the model, or this proves nothing"


def test_clearing_the_cell_returns_the_automatic_mark():
    """`last_tick=None` is a cleared cell, and it must restore the model price exactly --
    not a zero, which is a real price meaning the leg is worthless."""
    assert mark_of(a_call(last_tick=None)) == pytest.approx(mark_of(a_call()))
    assert mark_of(a_call(last_tick=0.0)) == pytest.approx(0.0), "0 is a price, not a clear"


def test_a_typed_mark_moves_pnl_and_nothing_else():
    """It is a valuation, not a position: P&L follows the mark, the greeks do not."""
    model = eval_position(a_call(), NEUTRAL, price_book, commodity=LIVE_CATTLE)
    typed = eval_position(a_call(last_tick=0.0260), NEUTRAL, price_book, commodity=LIVE_CATTLE)
    assert typed.pnl != pytest.approx(model.pnl)
    assert typed.pnl == pytest.approx((0.0260 - 0.0313) * 250 * LIVE_CATTLE.contract_size)
    for greek in ("delta_d", "gamma_d", "vega_d", "theta_d"):
        assert getattr(typed, greek) == pytest.approx(getattr(model, greek))


def test_a_stress_scenario_ignores_the_typed_mark():
    """Why the column is locked there -- this is `eval_position`'s own rule, not a new one."""
    assert mark_of(a_call(last_tick=0.0260), SHOCKED) == pytest.approx(mark_of(a_call(), SHOCKED))


def test_mark_is_in_the_editable_set_only_at_zero_stress():
    src = inspect.getsource(blotter.render_editable_blotter)
    tree = ast.parse(src.lstrip())
    assign = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "editable"
    )
    rendered = ast.unparse(assign)   # normalises quoting, so match on the bare names
    assert "Mark" in rendered and "is_neutral" in rendered, rendered
    assert "Qty" in rendered and "Entry" in rendered, "the existing two must survive"


def test_the_caption_names_exactly_what_is_editable():
    neutral, shocked = blotter.editable_caption(NEUTRAL), blotter.editable_caption(SHOCKED)
    assert "Mark" in neutral and "reset" in neutral.lower()
    assert "clear" not in neutral.lower(), (
        "clearing a NumberColumn cell does not reach edited_rows -- measured in a browser. "
        "A caption promising it is a promise the grid does not keep."
    )
    assert "locked" in shocked
    # The failure this guards: a caption promising an edit the grid will not accept.
    assert "Qty, Entry and Mark are editable" not in shocked


def test_there_is_a_way_back_from_a_manual_mark():
    """An override with no route back to the automatic price is a trap. The button is that
    route, it writes None to the same field, and it only appears when a manual mark
    exists."""
    src = inspect.getsource(blotter.render_editable_blotter)
    block = src[src.index("reset_manual_marks") - 600:]
    assert "p.last_tick is not None" in block, "offered only when something is overridden"
    assert '"LAST_TICK", None' in block, "and it must clear the same field Mark writes"


def test_a_cleared_cell_is_not_coerced_to_a_float():
    """`float(None)` raises; the handler must branch on None before converting. Read off
    the source because the write path needs a live st.session_state to call."""
    src = inspect.getsource(blotter.render_editable_blotter)
    block = src[src.index('if "Mark" in edits:'):]
    assert "None if raw is None else float(raw)" in block, block[:400]


def test_the_write_targets_last_tick_and_no_other_field():
    """If this ever points at a new column instead, the automatic mark stops being the
    fallback and the feature has quietly become something else."""
    src = inspect.getsource(blotter.render_editable_blotter)
    block = src[src.index('if "Mark" in edits:'):]
    assert '"LAST_TICK"' in block
    assert Path("src/jsa_risk/state.py").read_text(encoding="utf-8").count('"LAST_TICK": "last_tick"') == 1
