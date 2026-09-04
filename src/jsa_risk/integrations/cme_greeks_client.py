"""CME Options Analytics: Greeks/IV REST API client.

Unlike massive_client.py, there is no working browser implementation to port — CME's
token endpoint blocks direct browser requests via CORS, which is the entire reason this
project moved off a static HTML page. This client runs the OAuth client_credentials
handshake server-side, where CORS doesn't apply.

IMPORTANT — this is best-effort scaffolding, not a verified integration: corn's
entitlement on CME's product list was never confirmed, and the exact request/response
shape below (the `/latest` path, `symbol` param, and the response field names) is a
reasonable guess from the product's docs pattern, not something tested against a live
account. Before relying on this, get real credentials into `.streamlit/secrets.toml`
under `[cme_greeks]` and confirm the actual endpoint contract — then this file's request
params and `CmeGreeksResult` field mapping will likely need adjusting.

Every call here must fail soft: any error (auth, not entitled, unexpected response shape)
should read as "not available" to the caller, never crash the dashboard, per the plan's
own instruction to show CME Greeks side-by-side with the local Black-76 calc rather than
gate anything on it.
"""
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import requests

from jsa_risk.config import CmeGreeksConfig

DEFAULT_TOKEN_TTL_SECONDS = 30 * 60
_EARLY_REFRESH_SECONDS = 30

# Cache is process-wide (module-level), keyed by token_url+api_id — fine for a
# single-service-account Streamlit app; not per-viewer state.
_token_cache: Dict[Tuple[str, str], Tuple[str, float]] = {}


class CmeGreeksUnavailable(RuntimeError):
    """Raised for any failure fetching CME Greeks — auth, not entitled, network, or an
    unexpected response shape. Callers should catch this specifically and show
    "not available", not a raw traceback."""


@dataclass(frozen=True)
class CmeGreeksResult:
    iv: Optional[float]
    delta: Optional[float]
    gamma: Optional[float]
    vega: Optional[float]
    theta: Optional[float]
    as_of: Optional[str]


def _get_token(config: CmeGreeksConfig) -> str:
    cache_key = (config.token_url, config.api_id)
    cached = _token_cache.get(cache_key)
    now = time.time()
    if cached and cached[1] > now:
        return cached[0]
    try:
        resp = requests.post(
            config.token_url,
            data={"grant_type": "client_credentials"},
            auth=(config.api_id, config.password),
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        token = payload["access_token"]
    except Exception as e:
        raise CmeGreeksUnavailable(f"CME token request failed: {e}") from e
    expires_in = payload.get("expires_in", DEFAULT_TOKEN_TTL_SECONDS)
    _token_cache[cache_key] = (token, now + expires_in - _EARLY_REFRESH_SECONDS)
    return token


def fetch_greeks(config: CmeGreeksConfig, contract_symbol: str) -> CmeGreeksResult:
    """Best-effort: raises CmeGreeksUnavailable on any failure. See module docstring —
    the endpoint path/params/response fields are unverified."""
    token = _get_token(config)
    try:
        resp = requests.get(
            f"{config.base_url}/latest",
            params={"symbol": contract_symbol},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        raise CmeGreeksUnavailable(f"CME Greeks request failed for {contract_symbol}: {e}") from e
    return CmeGreeksResult(
        iv=payload.get("impliedVolatility"),
        delta=payload.get("delta"),
        gamma=payload.get("gamma"),
        vega=payload.get("vega"),
        theta=payload.get("theta"),
        as_of=payload.get("asOf"),
    )
