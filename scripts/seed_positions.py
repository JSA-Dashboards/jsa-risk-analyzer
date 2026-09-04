"""One-time seed: writes the same 10-position demo book used throughout development
into Snowflake's POSITIONS table via positions_repo.replace_book(), so Phase 2's
Snowflake-backed app starts from the same known-good state as Phase 1's session-state
version (and the original HTML tool).

Run with: .venv/Scripts/python.exe scripts/seed_positions.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jsa_risk.data import positions_repo
from jsa_risk.pricing.stress import Position


def in_days(n: int) -> date:
    return date.today() + timedelta(days=n)


SEED_POSITIONS = [
    Position(id=0, label="ZCU26", type="call", qty=-30, entry=0.21, strike=5.00,
             expiry_date=in_days(32), iv=25.20, iv_estimated=True, last_tick=0.020),
    Position(id=0, label="ZCU26", type="put", qty=30, entry=0.19, strike=4.30,
             expiry_date=in_days(32), iv=25.20, iv_estimated=True),
    Position(id=0, label="ZCU26", type="call", qty=15, entry=0.18, strike=4.70,
             expiry_date=in_days(32), iv=25.20, iv_estimated=True),
    Position(id=0, label="ZCZ26", type="put", qty=20, entry=0.22, strike=4.50,
             expiry_date=in_days(95), iv=23.43, iv_estimated=True),
    Position(id=0, label="ZCZ26", type="call", qty=-20, entry=0.15, strike=4.90,
             expiry_date=in_days(95), iv=23.43, iv_estimated=True),
    Position(id=0, label="ZCU26", type="future", qty=10, entry=4.55, last_tick=4.6525),
    Position(id=0, label="ZCZ26", type="future", qty=-8, entry=4.80),
    Position(id=0, label="ZCN27", type="call", qty=12, entry=0.24, strike=4.60,
             expiry_date=in_days(220), iv=21.50, iv_estimated=True),
    Position(id=0, label="ZCN27", type="future", qty=6, entry=4.50),
    Position(id=0, label="ZCV26", type="put", qty=10, entry=0.17, strike=4.55,
             expiry_date=in_days(63), iv=23.43, iv_estimated=True),
]


def main() -> int:
    batch_id = positions_repo.replace_book(
        SEED_POSITIONS, mapping=None, source_filename="seed_positions.py", imported_by="CJACOBS",
    )
    print(f"Replaced book with {len(SEED_POSITIONS)} positions (import batch {batch_id}).")
    loaded = positions_repo.load_positions()
    for p in loaded:
        print(f"  id={p.id} {p.label} {p.type} qty={p.qty} entry={p.entry}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
