"""CME Options Analytics: Greeks/IV REST API client.

Unlike massive_client.py, there is no working browser implementation to port — CME's
token endpoint blocks direct browser requests via CORS, which is the entire reason this
project moved off a static HTML page. This client runs the OAuth client_credentials
handshake server-side, where CORS doesn't apply.

Verified against the live API on 2026-09-11 with an entitled account. Three things the
docs get wrong or leave out, each of which cost real debugging time:

1. `productCodes` takes the OPTION code, not the underlying futures code — corn is
   "OZC", not "ZC". A futures code returns 403 "Not entitled to one or more of the
   requested productCodes", which reads like a licensing failure and is not. CME's
   product-list page tabulates underlying codes, which is what makes this easy to
   invert. Use `undlyProductCodes` if you really do want to filter by underlying.
2. `/latest` is NOT one cross-sectional snapshot. It returns each instrument's most
   recent snapshot, so transactTime varies per contract and an illiquid contract can be
   days stale inside a "latest" response — a live corn pull spanned four business dates.
   `_latest_by_contract` collapses to the newest per contract.
3. A `User-Agent` header is required on every data call.

IV arrives as a decimal (0.2332); IV_SNAPSHOT stores percent (23.32), so everything
leaving this module for that table is already multiplied by 100.

Every call here fails soft: any error (auth, not entitled, unexpected shape) raises
CmeGreeksUnavailable so callers can show "not available" rather than crash the
dashboard.
"""
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from jsa_risk.config import CmeGreeksConfig
from jsa_risk.pricing.symbols import CORN_MONTH_NAMES, QUARTERLY_MONTHS

DEFAULT_TOKEN_TTL_SECONDS = 30 * 60
_EARLY_REFRESH_SECONDS = 30
_MAX_PAGE_SIZE = 2000
_USER_AGENT = "JSA-Risk-Analyzer/1.0 (python-requests)"

# How far from 50 delta a fallback leg may sit before we decline to call it "ATM".
# 0.15 keeps roughly 35-65 delta; beyond that, skew makes the vol unrepresentative.
_NEAR_THE_MONEY_DELTA_TOLERANCE = 0.15

CORN_OPTION_PRODUCT = "OZC"

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


@dataclass(frozen=True)
class IvQuote:
    """One contract's at-the-money IV, ready for IV_SNAPSHOT."""
    canonical_key: str      # "Z26" — the underlying quarterly future
    iv_pct: float           # percent, e.g. 23.32
    as_of: str              # the snapshot's transactTime, NOT fetch time
    option_sym: str         # "OZCZ26"
    undly_sym: str          # "ZCZ26"
    undly_px: Optional[float]
    dte: Optional[float]
    method: str             # "ATM", or "~0.47d" when no ATM strike had a two-sided market

    @property
    def source_label(self) -> str:
        return f"CME Options Analytics {self.method} ({self.option_sym} @ {self.as_of})"


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


def _get(config: CmeGreeksConfig, path: str, params: dict) -> dict:
    token = _get_token(config)
    try:
        resp = requests.get(
            f"{config.base_url.rstrip('/')}/{path.lstrip('/')}",
            params={k: v for k, v in params.items() if v is not None},
            headers={"Authorization": f"Bearer {token}", "User-Agent": _USER_AGENT},
            timeout=30,
        )
        if resp.status_code == 403:
            raise CmeGreeksUnavailable(
                "CME returned 403. Either the API ID isn't entitled to Options "
                "Analytics, or a futures code was passed where an option code belongs "
                "(corn is OZC, not ZC)."
            )
        resp.raise_for_status()
        return resp.json()
    except CmeGreeksUnavailable:
        raise
    except Exception as e:
        raise CmeGreeksUnavailable(f"CME Greeks request failed ({path}): {e}") from e


def fetch_latest(config: CmeGreeksConfig, product_codes: Sequence[str]) -> List[dict]:
    """Raw /latest records, following nextPageCursor to the end."""
    out: List[dict] = []
    cursor = None
    while True:
        body = _get(config, "latest", {
            "productCodes": ",".join(product_codes),
            "pageSize": _MAX_PAGE_SIZE,
            "nextPageCursor": cursor,
        })
        out.extend(body.get("payload") or [])
        cursor = (body.get("metadata") or {}).get("nextPageCursor")
        if not cursor:
            return out


def _latest_by_contract(records: Iterable[dict]) -> List[dict]:
    """Keep only each contract's newest snapshot — see point 2 in the module docstring."""
    records = list(records or [])
    newest: Dict[str, str] = {}
    for rec in records:
        sym = (rec.get("instrument") or {}).get("sym")
        t = rec.get("transactTime")
        if sym and t and (sym not in newest or t > newest[sym]):
            newest[sym] = t
    return [r for r in records
            if r.get("transactTime") == newest.get((r.get("instrument") or {}).get("sym"))]


def _atm_iv(legs: Sequence[dict]) -> Optional[Tuple[float, str]]:
    """(iv_decimal, method) for one contract, or None if it has no usable leg.

    Prefers the mean of the ATM call and put. A strike only appears when it had a
    two-sided market at snapshot time, so a thin contract may have no ATM strike at all.
    There we fall back to whichever leg sits closest to 50 delta — but only if it is
    genuinely near the money. Because of skew a 19-delta vol is not a usable stand-in for
    at-the-money (live Z28 corn showed exactly that), and writing one into IV_SNAPSHOT as
    though it were the contract's vol would be quietly wrong. Outside the band we return
    None and leave that contract's row alone rather than guess.
    """
    atm = [l for l in legs if l.get("optStat") == "ATM" and l.get("impliedVol") is not None]
    if atm:
        return sum(l["impliedVol"] for l in atm) / len(atm), "ATM"
    priced = [l for l in legs if l.get("impliedVol") is not None and l.get("delta") is not None]
    if not priced:
        return None
    near = min(priced, key=lambda l: abs(abs(l["delta"]) - 0.5))
    if abs(abs(near["delta"]) - 0.5) > _NEAR_THE_MONEY_DELTA_TOLERANCE:
        return None
    return near["impliedVol"], f"~{abs(near['delta']):.2f}d"


def atm_iv_by_canonical_key(
    config: CmeGreeksConfig, product_code: str = CORN_OPTION_PRODUCT
) -> Dict[str, IvQuote]:
    """Live ATM IV per canonical contract key, e.g. {"Z26": IvQuote(iv_pct=23.32, ...)}.

    Only QUARTERLY option contracts are returned. IV_SNAPSHOT is keyed by the underlying
    future (symbols.canonical_contract_key maps serial months onto the next quarterly),
    so the Oct, Nov and Dec corn options all resolve to "Z26" and would overwrite each
    other. The quarterly option is the one whose expiry matches its underlying, so it is
    the defensible single value for that key.

    Caveat worth knowing: this means one IV per underlying, applied to serial options
    too. Short-dated serials genuinely trade at a different vol — on 2026-09-11 the Oct
    serial was 30.1% against December's 23.3% — so a serial position priced off this
    table is using a materially wrong vol. Fixing that needs a key scheme that keeps the
    option's own expiry, which is a larger change than this function.
    """
    records = _latest_by_contract(fetch_latest(config, [product_code]))
    quotes: Dict[str, IvQuote] = {}
    for rec in records:
        inst = rec.get("instrument") or {}
        sym = inst.get("sym") or ""
        # "OZCZ26" -> month "Z", year "26". Guard rather than assume the layout.
        tail = sym[len(product_code):]
        if len(tail) != 3:
            continue
        month, year2 = tail[0], tail[1:]
        if month not in CORN_MONTH_NAMES or month not in QUARTERLY_MONTHS or not year2.isdigit():
            continue
        got = _atm_iv(rec.get("values") or [])
        if not got:
            continue
        iv_decimal, method = got
        key = f"{month}{year2}"
        quote = IvQuote(
            canonical_key=key,
            iv_pct=round(iv_decimal * 100, 4),   # IV_SNAPSHOT.IV is NUMBER(8,4), percent
            as_of=rec.get("transactTime") or "",
            option_sym=sym,
            undly_sym=inst.get("undlySym") or "",
            undly_px=inst.get("undlyPx"),
            dte=inst.get("dte"),
            method=method,
        )
        # Defensive: if the same key somehow appears twice, keep the fresher snapshot.
        if key not in quotes or quote.as_of > quotes[key].as_of:
            quotes[key] = quote
    return quotes


def fetch_greeks(
    config: CmeGreeksConfig,
    contract_symbol: str,
    strike: Optional[float] = None,
    opt_type: Optional[str] = None,
) -> CmeGreeksResult:
    """CME's own Greeks for one option leg, for showing side-by-side with the local
    Black-76 calc. `contract_symbol` is the option symbol (e.g. "OZCZ26"); with no
    strike, returns the ATM leg. Raises CmeGreeksUnavailable on any failure."""
    body = _get(config, "latest", {"symbols": contract_symbol, "pageSize": _MAX_PAGE_SIZE})
    records = _latest_by_contract(body.get("payload") or [])
    if not records:
        raise CmeGreeksUnavailable(f"CME returned no data for {contract_symbol}")

    candidates = [(rec, leg) for rec in records for leg in (rec.get("values") or [])]
    if opt_type:
        want = "C" if str(opt_type).strip().lower().startswith("c") else "P"
        candidates = [(r, l) for r, l in candidates if l.get("putCallInd") == want]
    if strike is not None:
        exact = [(r, l) for r, l in candidates if l.get("strikePx") == strike]
        candidates = exact or sorted(
            candidates, key=lambda rl: abs((rl[1].get("strikePx") or 0) - strike)
        )[:1]
    else:
        candidates = [(r, l) for r, l in candidates if l.get("optStat") == "ATM"] or candidates[:1]
    if not candidates:
        raise CmeGreeksUnavailable(
            f"CME returned no matching leg for {contract_symbol} "
            f"{opt_type or ''} {strike if strike is not None else ''}".strip()
        )

    rec, leg = candidates[0]
    return CmeGreeksResult(
        iv=leg.get("impliedVol"), delta=leg.get("delta"), gamma=leg.get("gamma"),
        vega=leg.get("vega"), theta=leg.get("theta"), as_of=rec.get("transactTime"),
    )
