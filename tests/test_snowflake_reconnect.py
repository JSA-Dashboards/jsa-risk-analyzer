"""The cached Snowflake connection must survive its session expiring.

Before this, an expired session broke every page of the deployed app until someone
rebooted it (2026-09-21). These tests pin the recovery without touching Snowflake.
"""
from unittest.mock import MagicMock, patch

import pytest
from snowflake.connector.errors import ProgrammingError

import jsa_risk.data.snowflake_client as sf


def _expired(errno=390114):
    return ProgrammingError(msg="Authentication token has expired.", errno=errno)


def _conn(execute_side_effect=None, rows=None):
    cur = MagicMock()
    cur.execute.side_effect = execute_side_effect
    cur.fetch_pandas_all.return_value = rows
    conn = MagicMock()
    conn.is_closed.return_value = False
    conn.cursor.return_value = cur
    return conn, cur


def _patched(*connections):
    """get_connection returning each connection in turn, with a spy on .clear()."""
    getter = MagicMock(side_effect=list(connections))
    getter.clear = MagicMock()
    return patch.object(sf, "get_connection", getter), getter


@pytest.mark.parametrize("errno", [390110, 390112, 390113, 390114, 390115])
def test_expired_session_reconnects_once_and_returns_the_result(errno):
    stale, _ = _conn(execute_side_effect=_expired(errno))
    fresh, _ = _conn(rows="the dataframe")
    p, getter = _patched(stale, fresh)
    with p:
        assert sf.query_df("SELECT 1") == "the dataframe"
    getter.clear.assert_called_once()


def test_marker_on_the_exception_context_also_counts():
    # The connector raises the ProgrammingError from inside its ReauthenticationRequest
    # handler, so the expiry can show up only on __context__.
    class ReauthenticationRequest(Exception):
        pass

    err = ProgrammingError(msg="token request failed", errno=250001)
    err.__context__ = ReauthenticationRequest()
    stale, _ = _conn(execute_side_effect=err)
    fresh, _ = _conn(rows="ok")
    p, getter = _patched(stale, fresh)
    with p:
        assert sf.query_df("SELECT 1") == "ok"
    getter.clear.assert_called_once()


def test_an_ordinary_sql_error_is_not_retried():
    bad_sql = ProgrammingError(msg="SQL compilation error", errno=1003)
    conn, cur = _conn(execute_side_effect=bad_sql)
    p, getter = _patched(conn)
    with p, pytest.raises(ProgrammingError):
        sf.query_df("SELEC 1")
    getter.clear.assert_not_called()
    assert cur.execute.call_count == 1


def test_bad_request_code_is_not_treated_as_expiry():
    conn, _ = _conn(execute_side_effect=ProgrammingError(msg="bad request", errno=390400))
    p, getter = _patched(conn)
    with p, pytest.raises(ProgrammingError):
        sf.query_df("SELECT 1")
    getter.clear.assert_not_called()


def test_only_one_retry_so_a_persistent_failure_surfaces():
    first, _ = _conn(execute_side_effect=_expired())
    second, _ = _conn(execute_side_effect=_expired())
    p, getter = _patched(first, second)
    with p, pytest.raises(ProgrammingError):
        sf.query_df("SELECT 1")
    assert getter.call_count == 2


def test_a_closed_cached_connection_is_replaced_before_use():
    closed, closed_cur = _conn()
    closed.is_closed.return_value = True
    fresh, _ = _conn(rows="ok")
    p, getter = _patched(closed, fresh)
    with p:
        assert sf.query_df("SELECT 1") == "ok"
    getter.clear.assert_called_once()
    closed_cur.execute.assert_not_called()


def test_writes_recover_too():
    stale, _ = _conn(execute_side_effect=_expired())
    fresh, fresh_cur = _conn()
    p, _ = _patched(stale, fresh)
    with p:
        sf.execute("INSERT INTO POSITIONS VALUES (%s)", (1,))
    fresh_cur.execute.assert_called_once_with("INSERT INTO POSITIONS VALUES (%s)", (1,))


def test_executemany_recovers_and_skips_empty_batches():
    stale, _ = _conn()
    stale.cursor.return_value.executemany.side_effect = _expired()
    fresh, fresh_cur = _conn()
    p, getter = _patched(stale, fresh)
    with p:
        sf.executemany("INSERT INTO T VALUES (%s)", [(1,), (2,)])
        sf.executemany("INSERT INTO T VALUES (%s)", [])       # no connection needed
    fresh_cur.executemany.assert_called_once()
    assert getter.call_count == 2
