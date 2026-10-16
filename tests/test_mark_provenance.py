"""The futures-mark age caption and staleness warning.

The fault it exists for was silent: the mark only moves when somebody presses the Massive
button, and a week-old mark renders exactly like this morning's. Everything on the page
except the blotter is priced off it.
"""
import ast
import pathlib
from datetime import datetime

from jsa_risk.ui.market_strip import (
    MARK_STALE_AFTER_SESSIONS,
    sessions_since,
    summarize_mark_provenance,
)

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "jsa_risk"

MON = datetime(2026, 10, 12, 9, 0)
TUE = datetime(2026, 10, 13, 9, 0)
WED = datetime(2026, 10, 14, 9, 0)
THU = datetime(2026, 10, 15, 9, 0)
FRI = datetime(2026, 10, 16, 9, 0)
SAT = datetime(2026, 10, 17, 9, 0)
NEXT_MON = datetime(2026, 10, 19, 9, 0)


def row(key="G27", price=2.2935, source="massive", updated_at=THU):
    return {"key": key, "price": price, "source": source, "updated_at": updated_at}


def test_a_friday_mark_read_on_monday_is_one_session_old_not_three_days():
    """The whole reason this counts sessions. By the clock that mark is ~2.8 days old and
    is still the most recent settle there has been -- a calendar-day rule calls it stale
    every Monday, and a warning that fires every Monday is one nobody reads on the
    Tuesday it matters."""
    assert sessions_since(FRI, NEXT_MON) == 1
    assert sessions_since(FRI, SAT) == 0
    assert sessions_since(THU, FRI) == 1
    assert sessions_since(MON, THU) == 3
    assert sessions_since(THU, THU) == 0
    assert sessions_since(FRI, THU) == 0          # a future stamp is not negative sessions


def test_a_monday_morning_read_of_fridays_mark_does_not_warn():
    s = summarize_mark_provenance([row(updated_at=FRI)], in_book=set(), now=NEXT_MON)
    assert s["warning"] is None


def test_two_dead_sessions_warn_and_name_what_is_and_is_not_affected():
    """A reader looking at a moving blotter needs telling WHY the charts below it are
    not moving -- that split is what made this hard to diagnose in the first place."""
    s = summarize_mark_provenance([row(updated_at=MON)], in_book=set(), now=FRI)
    assert s["warning"] is not None
    assert "4 sessions old" in s["warning"]
    assert "blotter" in s["warning"] and "heatmap" in s["warning"].lower()
    assert "Massive" in s["warning"]


def test_the_age_is_stated_even_when_it_is_fresh():
    """Unconditionally, unlike the IV caption's warning. A line that only appears when
    something is wrong cannot be checked at a glance when you are wondering whether
    anything IS wrong -- which is the question that started this."""
    s = summarize_mark_provenance([row(updated_at=THU)], in_book=set(), now=THU)
    assert s["warning"] is None
    assert "2026-10-15" in s["caption"] and "Futures marks" in s["caption"]
    assert "massive" in s["caption"]


def test_a_mark_with_no_timestamp_warns_rather_than_passing_as_fresh():
    """`max()` over no dates returns None, and the easy mistake is to treat that as
    nothing to report -- which is precisely the silence being fixed."""
    s = summarize_mark_provenance([row(updated_at=None)], in_book=set(), now=THU)
    assert s["warning"] is not None and "cannot be checked" in s["warning"]
    assert "never updated" in s["caption"]


def test_one_lagging_contract_in_the_book_is_named():
    """The headline age reads off the NEWEST row, so one stale contract hides behind a
    neighbour that was refreshed this morning. In the blotter it is an ordinary-looking
    number with nothing to mark it out."""
    rows = [row(key="G27", updated_at=THU), row(key="J27", updated_at=MON)]
    s = summarize_mark_provenance(rows, in_book={"G27", "J27"}, now=THU)
    assert s["warning"] is None          # the book as a whole is current
    assert s["behind"] == ["J27"]        # ...but this leg is not


def test_a_lagging_contract_nobody_holds_is_not_reported():
    rows = [row(key="G27", updated_at=THU), row(key="Z26", updated_at=MON)]
    s = summarize_mark_provenance(rows, in_book={"G27"}, now=THU)
    assert s["behind"] == []


def test_an_empty_table_says_nothing_rather_than_warning():
    s = summarize_mark_provenance([], in_book={"G27"}, now=THU)
    assert s == {"caption": None, "warning": None, "behind": []}


def test_the_threshold_absorbs_a_single_exchange_holiday():
    """No holiday calendar is modelled, so a closed Friday makes Thursday's mark look a
    session older than it is. The threshold has to be wide enough that one holiday cannot
    raise a false alarm, or the first thing anyone learns is to ignore it."""
    assert MARK_STALE_AFTER_SESSIONS >= 2
    # Thursday's mark, read the Monday after a closed Friday: 2 counted sessions.
    s = summarize_mark_provenance([row(updated_at=THU)], in_book=set(), now=NEXT_MON)
    assert sessions_since(THU, NEXT_MON) == 2
    assert s["warning"] is None


def test_the_caption_is_rendered_before_the_iv_one_and_cannot_break_the_page():
    """It is a caption: a Snowflake hiccup must not take the dashboard down for it, which
    is the same bargain render_iv_provenance already makes."""
    body = (SRC / "ui" / "market_strip.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(body))
              if isinstance(n, ast.FunctionDef) and n.name == "render_mark_provenance")
    assert any(isinstance(n, ast.Try) for n in ast.walk(fn))

    page = (SRC.parents[1] / "pages" / "dashboard.py").read_text(encoding="utf-8")
    assert page.index("render_mark_provenance(") < page.index("render_iv_provenance(")


def test_refreshing_a_mark_clears_the_provenance_cache_too():
    """Both read the same row. Clearing one and not the other leaves the caption calling
    a mark a day old a second after somebody refreshed it."""
    body = (SRC / "data" / "reference_repo.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(body))
              if isinstance(n, ast.FunctionDef) and n.name == "set_contract_price")
    cleared = {ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)}
    assert "get_contract_marks.clear" in cleared
    assert "get_contract_mark_provenance.clear" in cleared
