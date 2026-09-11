"""Refresh IV_SNAPSHOT from the live CME Options Analytics feed.

Replaces the hand-typed vols seeded by seed_reference_data.py with at-the-money implied
vol pulled from CME, one row per quarterly corn contract.

    .venv/Scripts/python.exe scripts/refresh_iv_from_cme.py --dry-run
    .venv/Scripts/python.exe scripts/refresh_iv_from_cme.py
    .venv/Scripts/python.exe scripts/refresh_iv_from_cme.py --keys Z26 N27

Safe to run on a schedule. Each run is a MERGE, so it updates in place rather than
accumulating rows, and AS_OF records the snapshot's own timestamp — not the time the
script ran, which would make stale data look fresh.

Note the feed only publishes a snapshot for a contract that had a two-sided market, so
a thin deferred contract can legitimately carry a timestamp days old. That is visible in
AS_OF and in SOURCE rather than hidden.
"""
import argparse
import sys
import tomllib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cryptography.hazmat.primitives import serialization
import snowflake.connector

from jsa_risk.config import CmeGreeksConfig
from jsa_risk.integrations.cme_greeks_client import (
    CORN_OPTION_PRODUCT,
    CmeGreeksUnavailable,
    atm_iv_by_canonical_key,
)

ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"


def load_private_key_der(path: str) -> bytes:
    with open(path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def cme_config_from_secrets(secrets: dict) -> CmeGreeksConfig:
    if "cme_greeks" not in secrets:
        raise SystemExit(
            "No [cme_greeks] block in .streamlit/secrets.toml — see secrets.toml.example."
        )
    s = secrets["cme_greeks"]
    return CmeGreeksConfig(
        api_id=s["api_id"],
        password=s["password"],
        base_url=s.get("base_url", "https://markets.api.cmegroup.com/greeks/v1"),
        token_url=s.get("token_url", "https://auth.cmegroup.com/as/token.oauth2"),
    )


def parse_as_of(transact_time: str):
    """'2026-09-11T09:06:01Z' -> naive UTC datetime for a TIMESTAMP_NTZ column."""
    try:
        return datetime.strptime(transact_time, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be written, touch nothing")
    ap.add_argument("--keys", nargs="+", metavar="KEY",
                    help="only these canonical keys, e.g. Z26 N27 (default: all found)")
    ap.add_argument("--product", default=CORN_OPTION_PRODUCT,
                    help=f"CME option product code (default {CORN_OPTION_PRODUCT})")
    ap.add_argument("--updated-by", default="refresh_iv_from_cme")
    args = ap.parse_args(argv[1:])

    with open(SECRETS_PATH, "rb") as f:
        secrets = tomllib.load(f)

    try:
        quotes = atm_iv_by_canonical_key(cme_config_from_secrets(secrets), args.product)
    except CmeGreeksUnavailable as exc:
        print(f"CME feed unavailable: {exc}")
        return 2

    if args.keys:
        wanted = {k.upper() for k in args.keys}
        quotes = {k: v for k, v in quotes.items() if k in wanted}
        missing = wanted - set(quotes)
        if missing:
            print(f"WARNING: no live quote for {', '.join(sorted(missing))} "
                  f"— leaving those rows untouched")

    if not quotes:
        print("No quotes returned; nothing to write.")
        return 1

    print(f"{len(quotes)} contract(s) from CME:\n")
    print(f"  {'key':<5} {'IV %':>7} {'undly':<7} {'px':>9} {'dte':>7}  {'method':<7} snapshot")
    for key in sorted(quotes, key=lambda k: quotes[k].dte or 0):
        q = quotes[key]
        print(f"  {q.canonical_key:<5} {q.iv_pct:>7.2f} {q.undly_sym:<7} "
              f"{q.undly_px if q.undly_px is not None else '':>9} "
              f"{q.dte if q.dte is not None else '':>7}  {q.method:<7} {q.as_of}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    sf_cfg = secrets["snowflake"]
    conn = snowflake.connector.connect(
        account=sf_cfg["account"], user=sf_cfg["user"],
        private_key=load_private_key_der(sf_cfg["private_key_path"]),
        role=sf_cfg["role"], warehouse=sf_cfg["warehouse"],
        database=sf_cfg["database"], schema=sf_cfg["schema"],
    )
    try:
        cur = conn.cursor()
        for key in sorted(quotes):
            q = quotes[key]
            cur.execute(
                """
                MERGE INTO IV_SNAPSHOT t USING (SELECT %s AS KEY) s ON t.CANONICAL_KEY = s.KEY
                WHEN MATCHED THEN UPDATE SET IV=%s, SOURCE=%s, AS_OF=%s,
                                             UPDATED_AT=CURRENT_TIMESTAMP(), UPDATED_BY=%s
                WHEN NOT MATCHED THEN INSERT (CANONICAL_KEY, IV, SOURCE, AS_OF, UPDATED_BY)
                                  VALUES (%s, %s, %s, %s, %s)
                """,
                (q.canonical_key,
                 q.iv_pct, q.source_label, parse_as_of(q.as_of), args.updated_by,
                 q.canonical_key, q.iv_pct, q.source_label, parse_as_of(q.as_of),
                 args.updated_by),
            )
        conn.commit()
    finally:
        conn.close()

    print(f"\nWrote {len(quotes)} row(s) to IV_SNAPSHOT.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
