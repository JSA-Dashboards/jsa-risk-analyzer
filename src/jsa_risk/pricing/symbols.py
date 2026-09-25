"""CME/CBOT corn contract symbol decoding, ported from the JSA Risk Analyzer HTML tool.

The 3rd character of a corn symbol is the futures month code and the next two are the
2-digit year (e.g. "ZCZ26" -> Z, 26). Corn only lists futures in five "quarterly" months
(H/K/N/U/Z); every other month code only ever appears on a serial option — one that
expires in its own calendar month but is priced against the NEXT quarterly futures
contract.

A quarterly contract's own practical trading life ends well before its namesake calendar
month even begins (corn's last trade day is roughly two weeks earlier) — so once the
calendar reaches the 1st of a quarterly contract's own month, that contract is treated as
rolled off, and anything still nominally tied to it (its own monthly option, or a serial
option one hop away) rolls forward to the next quarterly contract instead, exactly like a
true serial option already does. This is date-dependent, so decoding takes an optional
`today` (defaults to the real today) — e.g. a September option prices off the September
future right up until Sep 1, then automatically prices off December from that point on.
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

CORN_MONTH_NAMES = {
    "F": "Jan", "G": "Feb", "H": "Mar", "J": "Apr", "K": "May", "M": "Jun",
    "N": "Jul", "Q": "Aug", "U": "Sep", "V": "Oct", "X": "Nov", "Z": "Dec",
}
CORN_MONTH_NUMBERS = {
    "F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
    "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12,
}
QUARTERLY_MONTHS = {"H", "K", "N", "U", "Z"}
QUARTERLY_ORDER = ["H", "K", "N", "U", "Z"]  # Mar, May, Jul, Sep, Dec -- cycles into next year after Z
SERIAL_TO_QUARTERLY = {"F": "H", "G": "H", "J": "K", "M": "N", "Q": "U", "V": "Z", "X": "Z"}


@dataclass(frozen=True)
class DecodedSymbol:
    raw: str
    expiry_month: str
    expiry_month_name: str
    year2: str                     # the option's own literal year, from the raw symbol
    is_serial: bool                # True whenever the underlying differs from the symbol's own month -- a true serial option, or a quarterly month that has itself rolled off
    underlying_month: str
    underlying_month_name: str
    underlying_year2: str          # the underlying contract's own year -- can differ from year2 when a roll crosses a year boundary (e.g. Dec -> Mar next year)
    underlying_key: str            # canonical key, e.g. "Z26"


def _next_quarterly(month: str, year: int) -> Tuple[str, int]:
    idx = QUARTERLY_ORDER.index(month)
    if idx == len(QUARTERLY_ORDER) - 1:
        return QUARTERLY_ORDER[0], year + 1
    return QUARTERLY_ORDER[idx + 1], year


def _roll_to_active_quarterly(month: str, year: int, today: date) -> Tuple[str, int]:
    """Cascades forward (not just one hop) so a long-stale reference still lands on
    whichever quarterly contract is actually current as of `today`."""
    while today >= date(year, CORN_MONTH_NUMBERS[month], 1):
        month, year = _next_quarterly(month, year)
    return month, year


def decode_contract_symbol(raw: Optional[str], today: Optional[date] = None) -> Optional[DecodedSymbol]:
    s = (raw or "").strip().upper()
    if len(s) < 5:
        return None
    month_char = s[2]
    year2 = s[3:5]
    if month_char not in CORN_MONTH_NAMES or not year2.isdigit():
        return None
    today = today or date.today()
    year = 2000 + int(year2)
    nominal_month = SERIAL_TO_QUARTERLY[month_char] if month_char not in QUARTERLY_MONTHS else month_char
    underlying_month, underlying_year = _roll_to_active_quarterly(nominal_month, year, today)
    is_serial = underlying_month != month_char
    return DecodedSymbol(
        raw=s,
        expiry_month=month_char,
        expiry_month_name=CORN_MONTH_NAMES[month_char],
        year2=year2,
        is_serial=is_serial,
        underlying_month=underlying_month,
        underlying_month_name=CORN_MONTH_NAMES[underlying_month],
        underlying_year2=f"{underlying_year % 100:02d}",
        underlying_key=f"{underlying_month}{underlying_year % 100:02d}",
    )


def canonical_contract_key(raw_label: Optional[str], today: Optional[date] = None) -> str:
    decoded = decode_contract_symbol(raw_label, today)
    return decoded.underlying_key if decoded else (raw_label or "").strip().upper()


def contract_display_name(raw_label: Optional[str], today: Optional[date] = None) -> str:
    decoded = decode_contract_symbol(raw_label, today)
    if not decoded:
        return (raw_label or "").strip().upper() or "—"
    name = f"{decoded.underlying_month_name} '{decoded.underlying_year2}"
    if decoded.is_serial:
        name += f" (via {decoded.expiry_month_name} option)"
    return name


def format_canonical_key(key: Optional[str]) -> str:
    """Formats an already-final canonical key (month letter + 2-digit year, e.g. "Z26")
    as a plain month name/year -- no serial-to-quarterly mapping and no date-based
    rolling, since a canonical key is by definition the underlying itself, not something
    that still needs to be resolved to one. Used for a manual underlying_override, which
    names its target directly rather than needing to be decoded from an option symbol."""
    s = (key or "").strip().upper()
    if len(s) != 3 or s[0] not in CORN_MONTH_NAMES or not s[1:].isdigit():
        return s or "—"
    return f"{CORN_MONTH_NAMES[s[0]]} '{s[1:]}"
