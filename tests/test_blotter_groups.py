"""The combined-by-underlying rows: what a client would otherwise work out by hand."""
import pathlib
from datetime import date

import pytest

from jsa_risk.pricing.commodities import LIVE_CATTLE
from jsa_risk.pricing.portfolio import book_totals, book_totals_by_group
from jsa_risk.pricing.stress import (
    Position, StressState, effective_underlying_display, eval_position,
)
from jsa_risk.ui.blotter import build_blotter_dataframe, fmt_combined_delta

G, J = date(2027, 2, 5), date(2027, 4, 2)
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
    assert feb.delta_per_unit == pytest.approx(0.5696, abs=1e-3)
    assert feb.delta_per_unit > 0.5            # NOT the naive sum of the printed cells
    assert abs(call_delta + put_delta) < 0.05  # ...which is near zero and would be wrong


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
    assert [g.label for g in groups(positions)] == list(dict.fromkeys(df["Underlying"]))
    assert [g.label for g in groups(positions)] == ["Feb '27", "Apr '27"]


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
