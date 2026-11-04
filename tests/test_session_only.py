"""state.session_only(): the admin portal's client view must not write shared reference data."""
from unittest.mock import patch

import pytest
import streamlit as st

from jsa_risk import state
from jsa_risk.data import reference_repo


class FakeSession(dict):
    """st.session_state: dict access plus attribute access."""
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e

    def __setattr__(self, k, v):
        self[k] = v


@pytest.fixture
def session(monkeypatch):
    s = FakeSession(commodity_code="ZC", positions=[])
    monkeypatch.setattr(st, "session_state", s)
    return s


def test_a_normal_session_still_writes_the_shared_mark(session):
    with patch.object(reference_repo, "set_contract_price") as shared:
        state.set_contract_price("Z26", 4.55)
    shared.assert_called_once()


def test_a_session_only_session_never_writes_the_shared_mark(session):
    session["_session_only"] = True
    with patch.object(reference_repo, "set_contract_price") as shared:
        state.set_contract_price("Z26", 4.55, source="manual")
    shared.assert_not_called()


def test_the_typed_price_still_takes_effect_for_that_viewer(session):
    session["_session_only"] = True
    with patch.object(reference_repo, "set_contract_price"), \
            patch.object(reference_repo, "get_contract_price", return_value=4.10) as shared_read, \
            patch.object(reference_repo, "get_contract_marks", return_value={"ZCZ26": 4.10, "ZCH27": 4.30}):
        assert state.get_contract_price("Z26") == 4.10       # nothing typed yet: the shared mark
        state.set_contract_price("Z26", 4.55)
        assert state.get_contract_price("Z26") == 4.55       # this viewer's own price wins
        assert state.get_contract_marks()["Z26"] == 4.55     # and the market strip sees it
        assert state.get_contract_marks()["H27"] == 4.30     # untouched contracts keep the shared mark
    shared_read.assert_called_once()


def test_another_session_never_sees_it(session, monkeypatch):
    session["_session_only"] = True
    with patch.object(reference_repo, "set_contract_price"):
        state.set_contract_price("Z26", 4.55)
    other = FakeSession(commodity_code="ZC", positions=[], _session_only=True)
    monkeypatch.setattr(st, "session_state", other)
    with patch.object(reference_repo, "get_contract_price", return_value=4.10):
        assert state.get_contract_price("Z26") == 4.10
