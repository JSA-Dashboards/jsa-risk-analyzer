"""CME/CBOT corn contract symbol decoding, ported from the JSA Risk Analyzer HTML tool.

The 3rd character of a corn symbol is the futures month code and the next two are the
2-digit year (e.g. "ZCZ26" -> Z, 26). Corn only lists futures in five "quarterly" months
(H/K/N/U/Z); every other month code only ever appears on a serial option — one that
expires in its own calendar month but is priced against the NEXT quarterly futures
contract.
"""
from dataclasses import dataclass
from typing import Optional

CORN_MONTH_NAMES = {
    "F": "Jan", "G": "Feb", "H": "Mar", "J": "Apr", "K": "May", "M": "Jun",
    "N": "Jul", "Q": "Aug", "U": "Sep", "V": "Oct", "X": "Nov", "Z": "Dec",
}
QUARTERLY_MONTHS = {"H", "K", "N", "U", "Z"}
SERIAL_TO_QUARTERLY = {"F": "H", "G": "H", "J": "K", "M": "N", "Q": "U", "V": "Z", "X": "Z"}


@dataclass(frozen=True)
class DecodedSymbol:
    raw: str
    expiry_month: str
    expiry_month_name: str
    year2: str
    is_serial: bool
    underlying_month: str
    underlying_month_name: str
    underlying_key: str  # canonical key, e.g. "Z26"


def decode_contract_symbol(raw: Optional[str]) -> Optional[DecodedSymbol]:
    s = (raw or "").strip().upper()
    if len(s) < 5:
        return None
    month_char = s[2]
    year2 = s[3:5]
    if month_char not in CORN_MONTH_NAMES or not year2.isdigit():
        return None
    is_serial = month_char not in QUARTERLY_MONTHS
    underlying_month = SERIAL_TO_QUARTERLY[month_char] if is_serial else month_char
    return DecodedSymbol(
        raw=s,
        expiry_month=month_char,
        expiry_month_name=CORN_MONTH_NAMES[month_char],
        year2=year2,
        is_serial=is_serial,
        underlying_month=underlying_month,
        underlying_month_name=CORN_MONTH_NAMES[underlying_month],
        underlying_key=underlying_month + year2,
    )


def canonical_contract_key(raw_label: Optional[str]) -> str:
    decoded = decode_contract_symbol(raw_label)
    return decoded.underlying_key if decoded else (raw_label or "").strip().upper()


def contract_display_name(raw_label: Optional[str]) -> str:
    decoded = decode_contract_symbol(raw_label)
    if not decoded:
        return (raw_label or "").strip().upper() or "—"
    name = f"{decoded.underlying_month_name} '{decoded.year2}"
    if decoded.is_serial:
        name += f" (via {decoded.expiry_month_name} option)"
    return name
