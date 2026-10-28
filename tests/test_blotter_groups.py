"""The combined-by-underlying rows: what a client would otherwise work out by hand."""
import pathlib
from datetime import date, timedelta

import pytest

from jsa_risk.pricing.commodities import LIVE_CATTLE
from jsa_risk.pricing.portfolio import book_totals, book_totals_by_group
from jsa_risk.pricing.stress import (
    Position, StressState, effective_underlying_display, eval_position,
)
from jsa_risk.ui.blotter import build_blotter_dataframe, fmt_combined_delta

# Expiries are RELATIVE to today, not fixed dates. `build_blotter_dataframe` has no
# `today` parameter and always uses date.today(), so a fixed expiry makes every
# delta in these fixtures decay as the calendar moves and any assertion about one
# true only on the day it was written -- which is exactly how these broke overnight.
G = date.today() + timedelta(days=113)
J = date.today() + timedelta(days=169)
SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "jsa_risk"


def price_book(_k):
    return 2.2935


def a_book():
    return [
        Position(id=1, label="LEG27", type="put", qty=-160, entry=0.0351, strike=2.19,
                 expiry_date=G, iv=14.0656, last_tick=0.0330),
        Position(id=2, label="LEG27", type="call", qty=160, entry=0.0313, strike=2.39,
                 expiry_date=G, iv=14.0656, last_tick=0.0323),
        Position(id=3, label="LEJ27", type="put", qty=-160, entry=0.0496, strike=2.20,
                 expiry_date=J, iv=14.1942, last_tick=0.0488),
        Position(id=4, label="LEJ27", type="call", qty=160, entry=0.0475, strike=2.40,
                 expiry_date=J, iv=14.1942, last_tick=0.0485),
    ]


def evals(positions):
    return [eval_position(p, StressState(), price_book, commodity=LIVE_CATTLE) for p in positions]


def groups(positions):
    return book_totals_by_group(positions, evals(positions),
                                lambda p: effective_underlying_display(p, commodity=LIVE_CATTLE))


def test_the_combined_delta_is_what_the_client_would_add_by_hand():
    """Long the 2.39 call at +0.2749 against SHORT the 2.19 put at -0.2939: being short
    makes the put's contribution +0.2939, so the structure is ~0.57 delta. That flip is
    the arithmetic this row exists to save, and getting its sign wrong would read as a
    near-flat 0.02 structure instead."""
    df = build_blotter_dataframe(a_book(), StressState(), price_book, commodity=LIVE_CATTLE)
    feb = groups(a_book())[0]
    call_delta = df["Delta"].iloc[1]
    put_delta = df["Delta"].iloc[0]
    assert put_delta < 0 < call_delta
    assert feb.delta_per_unit == pytest.approx(call_delta - put_delta, abs=1e-3)
    # A BAND, not a pinned 0.5696: these expiries are fixed dates, so the figure decays a
    # little every day the suite runs. Pinning it made this test true on the day it was
    # written and false the next morning.
    assert 0.50 < feb.delta_per_unit < 0.65
    assert abs(call_delta + put_delta) < 0.05  # the naive sum is near zero, and is wrong


def test_the_per_unit_delta_scales_to_the_position_column_beside_it():
    for g in groups(a_book()):
        assert g.delta_contracts * LIVE_CATTLE.contract_size == pytest.approx(g.position, rel=2e-4)
        assert g.delta_per_unit * 160 == pytest.approx(g.delta_contracts, rel=1e-9)


def test_rows_foot_the_book_line_beneath_them():
    positions = a_book()
    net_delta, total_pnl = book_totals(evals(positions))
    gs = groups(positions)
    assert sum(g.position for g in gs) == net_delta
    assert sum(g.pnl for g in gs) == total_pnl


def test_mixed_lot_sizes_have_no_per_unit_delta_and_say_so():
    """Two legs of different size are not N copies of one structure, so "0.57 delta" would
    be a number describing nothing. The row reports the legs' deltas added with their
    sizes, and labels them as deltas rather than leaving a bare figure in a column of
    per-unit ones."""
    book = a_book()[:2]
    book[1] = Position(id=2, label="LEG27", type="call", qty=80, entry=0.0313, strike=2.39,
                       expiry_date=G, iv=14.0656, last_tick=0.0323)
    g = groups(book)[0]
    assert g.delta_per_unit is None
    assert g.delta_contracts != 0
    assert fmt_combined_delta(g).endswith(" deltas")
    assert "+" in fmt_combined_delta(g)


def test_a_zero_qty_group_does_not_divide_by_zero():
    book = [Position(id=1, label="LEG27", type="call", qty=0, entry=0.03, strike=2.39,
                     expiry_date=G, iv=14.0656)]
    g = groups(book)[0]
    assert g.delta_per_unit is None and g.delta_contracts == 0


def test_groups_read_in_blotter_order_and_use_its_wording():
    positions = a_book()
    df = build_blotter_dataframe(positions, StressState(), price_book, commodity=LIVE_CATTLE)
    labels = [g.label for g in groups(positions)]
    # The PROPERTY, not the literal months. What matters is that the breakdown uses the
    # Underlying column's own wording in the column's own order; the wording itself comes
    # from the contract-roll rule in symbols.py and legitimately changes as months roll,
    # so asserting "Feb '27" pins this test to a window of the calendar instead of to the
    # behaviour it is checking.
    assert labels == list(dict.fromkeys(df["Underlying"]))
    assert len(labels) == 2 and len(set(labels)) == 2


def test_a_single_group_prints_no_breakdown():
    body = (SRC / "ui" / "blotter.py").read_text(encoding="utf-8")
    assert "if len(groups) > 1:" in body
    assert len(groups(a_book()[:2])) == 1


def test_the_rows_sit_above_the_book_line():
    """Parts then whole. The book line is what the KPI tile and the rest of the page
    quote, so it is the one that should be last on screen."""
    body = (SRC / "ui" / "blotter.py").read_text(encoding="utf-8")
    assert body.index("Combined by underlying") < body.index('_totals_html("Net Position"')


def test_the_greeks_bar_and_the_group_row_cannot_print_different_pounds():
    """Same quantity, two surfaces, inches apart on the page -- so they must round the
    same way. The bars sum per EXPIRY and these rows per UNDERLYING, which coincide
    whenever a contract carries one expiry; where they coincide the figure has to match to
    the pound, and it did not until both rounded per position."""
    from jsa_risk.ui.charts import _group_by_contract, _contract_group_key
    positions = a_book()
    ev = {id(p): e for p, e in zip(positions, evals(positions))}
    order, by_expiry = _group_by_contract(positions, ev, lambda r: round(r.delta_d))
    by_underlying = {g.label: g.position for g in groups(positions)}
    assert sorted(by_expiry.values()) == sorted(by_underlying.values())
    assert sum(by_expiry.values()) == sum(by_underlying.values())


def test_the_bar_labels_are_not_clipped_by_the_axis():
    """`cliponaxis=False` plus a side margin sized to the longest label. Without both, a
    long value loses its last characters at the axis edge and still reads as a number --
    "+7,391,811 lb" rendering as "+7,391,81", which no text-based check can see."""
    from jsa_risk.ui.charts import _label_margin_px
    body = (SRC / "ui" / "charts.py").read_text(encoding="utf-8")
    assert "cliponaxis=False" in body
    assert 'textposition="auto"' in body        # the part that saves a narrow window
    assert "margin=dict(l=side, r=side" in body
    assert _label_margin_px(["+36,453,427 lb"]) > _label_margin_px(["+$390"])
    assert _label_margin_px([]) == 10
    # capped, or three charts in a row leave no plot between their own margins
    assert _label_margin_px(["+1,234,567,890,123,456 lb"]) <= 70


def _one_underlying():
    """Ross's 2026-10-28 book: one strangle, both legs on Feb '27."""
    return [
        Position(id=1, label="LEG27", type="call", qty=100, entry=0.0275, strike=2.44,
                 expiry_date=G, iv=14.1226, last_tick=0.0275),
        Position(id=2, label="LEG27", type="put", qty=-100, entry=0.0340, strike=2.24,
                 expiry_date=G, iv=15.0600, last_tick=0.0340),
    ]


def test_a_single_underlying_book_still_reports_its_combined_delta():
    """The breakdown rows are suppressed for one group because they would repeat the
    book line's Position and P&L -- but the book line has never carried a DELTA, so
    suppressing them left the combined figure nowhere on the page for a book held in
    one contract. Which is what building a single strangle looks like."""
    book = _one_underlying()
    assert len(groups(book)) == 1
    g = groups(book)[0]
    assert g.delta_per_unit is not None
    assert 0.4 < g.delta_per_unit < 0.7          # a long call against a short put
    body = (SRC / "ui" / "blotter.py").read_text(encoding="utf-8")
    assert 'if len(groups) == 1:' in body
    assert '_totals_html("Combined Delta"' in body


def test_the_book_line_delta_is_the_group_delta_not_a_second_calculation():
    """One figure, one function. The book line and the breakdown must read the same
    `fmt_combined_delta` off the same GroupTotals, or a one-underlying book and a
    two-underlying one would quote this structure differently."""
    import ast
    body = (SRC / "ui" / "blotter.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(body))
              if isinstance(n, ast.FunctionDef) and n.name == "render_blotter_totals")
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "fmt_combined_delta"]
    assert len(calls) == 2, "the rows and the book line, and nothing else"
    # Both arguments come out of `groups` -- directly in the row comprehension, and via
    # `g = groups[0]` on the book line. What matters is that neither branch reaches past
    # GroupTotals and does its own delta arithmetic, so no attribute of it is formatted
    # anywhere in this function.
    src = ast.unparse(fn)
    assert "g = groups[0]" in src
    assert "delta_per_unit" not in src and "delta_contracts" not in src.replace(
        "_sign_style_color(g.delta_contracts)", "")


def test_several_underlyings_keep_the_delta_on_the_rows_and_off_the_book_line():
    """Deltas on different futures contracts do not add, so there is no book-level
    combined delta to print once more than one underlying is held -- the per-group
    rows are the only honest place for it."""
    book = a_book()                      # Feb '27 and Apr '27
    assert len(groups(book)) == 2
    body = (SRC / "ui" / "blotter.py").read_text(encoding="utf-8")
    i_rows = body.index("if len(groups) > 1:")
    i_line = body.index("if len(groups) == 1:")
    assert i_rows < i_line               # rows first, then the book line
    # the two branches are exclusive, so a two-group book cannot reach the book-line delta
    assert "elif" not in body[i_rows:i_line]


def test_the_book_line_delta_degrades_with_mixed_lot_sizes():
    """Same rule as the rows: no single structure to be one unit of, so it reports the
    legs' deltas added with their sizes and says "deltas" out loud rather than printing
    a per-unit figure for something that has no unit."""
    book = _one_underlying()
    book[1] = Position(id=2, label="LEG27", type="put", qty=-40, entry=0.0340, strike=2.24,
                       expiry_date=G, iv=15.0600, last_tick=0.0340)
    g = groups(book)[0]
    assert len(groups(book)) == 1
    assert g.delta_per_unit is None
    assert fmt_combined_delta(g).endswith(" deltas")
