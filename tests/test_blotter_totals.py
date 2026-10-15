"""The blotter's totals footer, and the thing it must not become: a second, independent
sum of a figure the KPI strip already prints at the top of the same page."""
import ast
import pathlib
from datetime import date

from jsa_risk.pricing.commodities import LIVE_CATTLE
from jsa_risk.pricing.portfolio import book_totals
from jsa_risk.pricing.stress import Position, StressState, eval_position
from jsa_risk.ui.blotter import build_blotter_dataframe

TODAY = date(2026, 10, 15)
F = 2.2935
EXPIRY = date(2027, 2, 5)
SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "jsa_risk"


def price_book(_key):
    return F


def a_book():
    """Ross's leg27/LEJ27 book: two strangles, long calls against short puts."""
    return [
        Position(id=1, label="LEG27", type="put", qty=-160, entry=0.0351, strike=2.19,
                 expiry_date=EXPIRY, iv=14.0656),
        Position(id=2, label="LEG27", type="call", qty=160, entry=0.0313, strike=2.39,
                 expiry_date=EXPIRY, iv=14.0656),
        Position(id=3, label="LEJ27", type="put", qty=-160, entry=0.0496, strike=2.20,
                 expiry_date=date(2027, 4, 2), iv=14.1942),
        Position(id=4, label="LEJ27", type="call", qty=160, entry=0.0475, strike=2.40,
                 expiry_date=date(2027, 4, 2), iv=14.1942),
    ]


def _evals(positions):
    return [eval_position(p, StressState(), price_book, today=TODAY, commodity=LIVE_CATTLE)
            for p in positions]


def test_totals_foot_the_columns_they_sit_under_exactly():
    """Ross's rule, and the whole point of a totals line: add the printed cells by hand and
    you get the printed total, to the dollar. Not within a rounding step -- EXACTLY."""
    positions = a_book()
    evals = _evals(positions)
    net_delta, total_pnl = book_totals(evals)
    df = build_blotter_dataframe(positions, StressState(), price_book, commodity=LIVE_CATTLE)
    assert net_delta == df["Delta (lb)"].sum()
    assert total_pnl == df["P&L"].sum()


def test_summing_unrounded_would_not_have_footed():
    """The rejected alternative, kept as arithmetic rather than as a claim: summing the raw
    values and rounding once lands off the column sum, so nobody re-derives it as 'cleaner'
    and quietly reintroduces a total that does not add up."""
    evals = _evals(a_book())
    rounded = sum(round(e.pnl) for e in evals)
    unrounded = round(sum(e.pnl for e in evals))
    assert abs(unrounded - rounded) <= len(evals) / 2   # small...
    assert book_totals(evals)[1] == rounded             # ...and we take the one that foots


def test_an_empty_book_totals_to_zero_rather_than_raising():
    assert book_totals([]) == (0, 0)


def test_the_footer_and_the_kpi_strip_cannot_drift():
    """"Net Position" in the KPI strip and "Total Delta (lb)" under the blotter are the
    same figure on the same page. Both must read it from `book_totals` -- a local
    `sum(e.delta_d ...)` in either file is how two defensible numbers start disagreeing."""
    for name in ("kpi.py", "blotter.py"):
        body = (SRC / "ui" / name).read_text(encoding="utf-8")
        tree = ast.parse(body)
        assert "book_totals" in body, f"{name} must take its net delta from book_totals"
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Name) and node.func.id == "sum"):
                continue
            src = ast.get_source_segment(body, node) or ""
            assert "delta_d" not in src, f"{name} re-sums delta_d at line {node.lineno}: {src}"


def test_the_totals_are_not_a_row_in_the_editor():
    """A totals row inside `st.data_editor` would sit in the same row-index space the edit
    handler maps back to positions by `df.iloc[row_idx]["id"]`, so it would be editable,
    deletable, and would raise on int(None) the moment its Delete box was ticked."""
    body = (SRC / "ui" / "blotter.py").read_text(encoding="utf-8")
    tree = ast.parse(body)
    builder = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "build_blotter_dataframe")
    appends = [n for n in ast.walk(builder)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "append"]
    assert len(appends) == 1, "the frame should gain one row per position and nothing else"

    totals = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "render_blotter_totals")
    calls = {n.func.attr for n in ast.walk(totals)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "data_editor" not in calls and "dataframe" not in calls


def test_both_totals_name_the_column_they_total():
    """A bare pair of numbers under a fifteen-column table does not say what it is
    totalling -- the standing rule that a figure has to read on its own."""
    body = (SRC / "ui" / "blotter.py").read_text(encoding="utf-8")
    assert 'f"Total {_delta_col(commodity)}"' in body   # "Total Delta (lb)" / "(bu)"
    assert '"Total P&L"' in body


def test_the_totals_are_punctuated_like_the_columns_they_sit_under():
    """The Delta and P&L columns are `%,d` and `$%,d`: no plus sign on a positive, a plain
    minus on a negative. A total formatted differently from the cells above it reads as a
    different kind of number -- and parentheses would be worse still, since in USDA and
    CFTC reports they mean NEGATIVE."""
    from jsa_risk.ui.blotter import fmt_total_delta, fmt_total_pnl
    assert fmt_total_delta(7735401, "lb") == "7,735,401 lb"
    assert fmt_total_delta(-7735401, "lb") == "-7,735,401 lb"
    assert fmt_total_delta(0, "bu") == "0 bu"
    assert fmt_total_pnl(62597) == "$62,597"
    assert fmt_total_pnl(-62597) == "-$62,597"
    assert "(" not in fmt_total_pnl(-1) and "+" not in fmt_total_pnl(1)


def test_the_totals_are_colored_by_sign_like_the_cells_above():
    from jsa_risk.ui.blotter import GAIN_COLOR, LOSS_COLOR, _sign_style_color
    assert _sign_style_color(1) == _sign_style_color(0) == GAIN_COLOR
    assert _sign_style_color(-1) == LOSS_COLOR
