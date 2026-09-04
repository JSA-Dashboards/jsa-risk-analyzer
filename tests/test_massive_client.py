import json
from unittest.mock import patch

import pytest

from jsa_risk.config import MassiveConfig
from jsa_risk.integrations.massive_client import (
    canonical_key_to_massive_ticker,
    fetch_futures_prices,
)

CONFIG = MassiveConfig(api_key="test-key", base_url="https://api.massive.test")


def test_canonical_key_to_massive_ticker_takes_month_letter_and_last_year_digit():
    assert canonical_key_to_massive_ticker("Z26") == "ZCZ6"
    assert canonical_key_to_massive_ticker("N27") == "ZCN7"


def _fake_response(status_code, body_text):
    class _Resp:
        def __init__(self):
            self.status_code = status_code
            self.text = body_text
            self.ok = 200 <= status_code < 300

    return _Resp()


def test_fetch_futures_prices_converts_cents_to_dollars_and_matches_by_month_year():
    body = json.dumps({
        "status": "OK",
        "results": [
            {"details": {"ticker": "ZCZ6"}, "last_trade": {"price": 480.0, "timeframe": "DELAYED"}},
            {"details": {"ticker": "ZCN7"}, "last_trade": {"price": 455.5, "timeframe": "DELAYED"}},
        ],
    })
    with patch("jsa_risk.integrations.massive_client.requests.get", return_value=_fake_response(200, body)) as mock_get:
        result = fetch_futures_prices(CONFIG, ["Z26", "N27"])
    assert result.updated == {"Z26": 4.80, "N27": 4.555}
    assert result.timeframe == "DELAYED"
    mock_get.assert_called_once()


def test_fetch_futures_prices_ignores_keys_that_dont_look_canonical():
    body = json.dumps({"status": "OK", "results": []})
    with patch("jsa_risk.integrations.massive_client.requests.get", return_value=_fake_response(200, body)):
        result = fetch_futures_prices(CONFIG, ["not-a-key", "", "Z26"])
    assert result.updated == {}


def test_fetch_futures_prices_returns_empty_without_calling_out_when_no_valid_keys():
    with patch("jsa_risk.integrations.massive_client.requests.get") as mock_get:
        result = fetch_futures_prices(CONFIG, [])
    assert result.updated == {}
    mock_get.assert_not_called()


def test_fetch_futures_prices_retries_once_on_non_json_body_then_succeeds():
    ok_body = json.dumps({"status": "OK", "results": [
        {"details": {"ticker": "ZCZ6"}, "last_trade": {"price": 480.0}},
    ]})
    responses = [_fake_response(200, "upstream hiccup, not json"), _fake_response(200, ok_body)]
    with patch("jsa_risk.integrations.massive_client.requests.get", side_effect=responses), \
         patch("jsa_risk.integrations.massive_client.time.sleep") as mock_sleep:
        result = fetch_futures_prices(CONFIG, ["Z26"])
    assert result.updated == {"Z26": 4.80}
    mock_sleep.assert_called_once()


def test_fetch_futures_prices_raises_original_error_after_second_failure():
    with patch("jsa_risk.integrations.massive_client.requests.get",
               return_value=_fake_response(200, "still not json")), \
         patch("jsa_risk.integrations.massive_client.time.sleep"):
        with pytest.raises(RuntimeError, match="non-JSON"):
            fetch_futures_prices(CONFIG, ["Z26"])


def test_fetch_futures_prices_raises_on_error_status_payload():
    body = json.dumps({"status": "ERROR", "error": "rate limited"})
    with patch("jsa_risk.integrations.massive_client.requests.get", return_value=_fake_response(200, body)), \
         patch("jsa_risk.integrations.massive_client.time.sleep"):
        with pytest.raises(RuntimeError, match="rate limited"):
            fetch_futures_prices(CONFIG, ["Z26"])
