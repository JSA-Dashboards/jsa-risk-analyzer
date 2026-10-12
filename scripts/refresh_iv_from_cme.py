"""Refresh IV_SNAPSHOT from CME DataMine end-of-day options settlements (corn and live
cattle).

Replaces the hand-typed vols seeded by seed_reference_data.py with at-the-money
settlement implied vol, one row per listed futures contract. `--commodity` picks ZC (corn,
the default, so existing scheduled runs are unchanged), LE (live cattle), or ALL.
Feeder cattle has no readable DataMine file under JSA's license.

    .venv/Scripts/python.exe scripts/refresh_iv_from_cme.py --dry-run
    .venv/Scripts/python.exe scripts/refresh_iv_from_cme.py
    .venv/Scripts/python.exe scripts/refresh_iv_from_cme.py --date 20260918 --settlement final
    .venv/Scripts/python.exe scripts/refresh_iv_from_cme.py --keys Z26 N27
    .venv/Scripts/python.exe scripts/refresh_iv_from_cme.py --commodity ALL

Source changed 2026-09-20: this used to read the Options Analytics Greeks REST API, which
JSA isn't licensed for (it 403s). JSA's license is DataMine End of Market Summary, whose
daily files carry each option's settlement IV. See integrations/cme_datamine_client.py.

With no --date, it takes the newest posted file: walking back from today, newest date
first, Final before Preliminary. So an evening run writes that day's Preliminary, and the
next morning's run upgrades it to the Final once CME posts it (~10:00 CT).

Safe to run on a schedule. Each run is a MERGE, so it updates in place rather than
accumulating rows. AS_OF is the settlement's trade date (00:00, since a settlement is a
daily value, not an instant) — never the time the script ran, which would make an old
file look fresh. A row is only overwritten by data at least as new as what it holds, so
back-filling with --date can't clobber a fresher value.
"""
import argparse
import sys
import tomllib
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jsa_risk.pricing.commodities import COMMODITIES, reference_key
from jsa_risk.pricing.symbols import MONTH_NUMBERS
from jsa_risk.integrations.cme_datamine_client import (
    DATAMINE_PRODUCTS,
    config_from_dict,
    CmeDataMineUnavailable,
    FileNotPosted,
    atm_iv_by_canonical_key,
    download_eod,
    latest_available,
    parse_eod_csv,
)

ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
CHICAGO = ZoneInfo("America/Chicago")
SETTLEMENT_CHOICES = {"auto": ("F", "P"), "final": ("F",), "prelim": ("P",)}


def load_private_key_der(path: str) -> bytes:
    from cryptography.hazmat.primitives import serialization
    with open(path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def load_private_key_der_from_pem(pem: str) -> bytes:
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def parse_date_arg(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYYMMDD, got {s!r}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be written, touch nothing")
    ap.add_argument("--commodity", default="ZC", choices=sorted(DATAMINE_PRODUCTS) + ["ALL"],
                    help="ZC corn (default), LE live cattle, or ALL")
    ap.add_argument("--keys", nargs="+", metavar="KEY",
                    help="only these canonical keys, e.g. Z26 N27 (default: all found)")
    ap.add_argument("--date", type=parse_date_arg, metavar="YYYYMMDD",
                    help="a specific trade date (default: newest posted file)")
    ap.add_argument("--settlement", choices=sorted(SETTLEMENT_CHOICES), default="auto",
                    help="final, prelim, or auto = Final if posted else Preliminary")
    ap.add_argument("--lookback-days", type=int, default=7,
                    help="how far back to search when --date is not given (default 7)")
    ap.add_argument("--updated-by", default="refresh_iv_from_cme")
    args = ap.parse_args(argv[1:])

    with open(SECRETS_PATH, "rb") as f:
        secrets = tomllib.load(f)
    if "cme_datamine" not in secrets:
        print("No [cme_datamine] block in .streamlit/secrets.toml - see secrets.toml.example.")
        return 2
    config = config_from_dict(secrets["cme_datamine"])
    wanted_settlements = SETTLEMENT_CHOICES[args.settlement]

    codes = sorted(DATAMINE_PRODUCTS) if args.commodity == "ALL" else [args.commodity]
    to_write = []        # (CommoditySpec, {canonical_key: EodIvQuote})
    for code in codes:
        spec = COMMODITIES[code]
        product = DATAMINE_PRODUCTS[code]
        try:
            if args.date:
                text = None
                for st_ in wanted_settlements:
                    try:
                        text = download_eod(config, args.date, st_, product.symbol, product.exchange)
                        trade_date, settlement = args.date, st_
                        break
                    except FileNotPosted:
                        continue
                if text is None:
                    print(f"[{code}] No {args.settlement} settlement file posted for {args.date:%Y-%m-%d}.")
                    continue
            else:
                today = datetime.now(CHICAGO).date()
                trade_date, settlement, text = latest_available(
                    config, today, args.lookback_days, wanted_settlements,
                    product.symbol, product.exchange)
        except CmeDataMineUnavailable as exc:
            print(f"[{code}] CME DataMine unavailable: {exc}")
            if len(codes) == 1:
                return 2
            continue

        rows = parse_eod_csv(text)
        month_letters = {MONTH_NUMBERS[m]: m for m in spec.listed_months}
        quotes = atm_iv_by_canonical_key(
            rows, settlement, trade_date, month_letters=month_letters, commodity_code=code,
            strike_divisor=product.strike_divisor, settlement_divisor=product.settlement_divisor)
        print(f"[{code} {spec.name}] File: {trade_date:%Y-%m-%d} "
              f"{'Final' if settlement == 'F' else 'Preliminary'} - {len(rows)} rows, "
              f"{len(quotes)} contract(s) with a usable ATM vol\n")

        if args.keys:
            wanted = {k.upper() for k in args.keys}
            quotes = {k: v for k, v in quotes.items() if k in wanted}
            missing = wanted - set(quotes)
            if missing:
                print(f"WARNING: no ATM vol for {', '.join(sorted(missing))} "
                      f"- leaving those rows untouched\n")

        if not quotes:
            print(f"[{code}] No quotes to write.\n")
            continue

        print(f"  {'key':<5} {'IV %':>7} {'undly':<7} {'implied px':>11} {'dte':>5} "
              f"{'ATM K':>7}  method")
        for key in sorted(quotes, key=lambda k: quotes[k].dte if quotes[k].dte is not None else 0):
            q = quotes[key]
            px = f"{q.undly_px:.3f}" if q.undly_px is not None else ""
            dte = q.dte if q.dte is not None else ""
            print(f"  {q.canonical_key:<5} {q.iv_pct:>7.2f} {q.undly_sym:<7} {px:>11} {dte:>5} "
                  f"{q.atm_strike:>7g}  {q.method}")
        print()
        to_write.append((spec, quotes))

    if not to_write:
        print("Nothing to write.")
        return 1

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    import snowflake.connector
    sf_cfg = secrets["snowflake"]
    auth = {}
    if sf_cfg.get("private_key_path"):
        auth["private_key"] = load_private_key_der(sf_cfg["private_key_path"])
    elif sf_cfg.get("private_key_pem"):
        auth["private_key"] = load_private_key_der_from_pem(sf_cfg["private_key_pem"])
    elif sf_cfg.get("password"):
        # Password auth is accepted here but NOT by jsa_risk.config, which the app uses:
        # Streamlit Cloud gets key-pair only. This script also runs from a laptop or a
        # scheduler against the same account, where key-pair may not be set up yet.
        auth["password"] = sf_cfg["password"]
    else:
        print("No Snowflake credential in [snowflake]: set private_key_path, "
              "private_key_pem, or password.")
        return 2
    conn = snowflake.connector.connect(
        account=sf_cfg["account"], user=sf_cfg["user"],
        role=sf_cfg["role"], warehouse=sf_cfg["warehouse"],
        database=sf_cfg["database"], schema=sf_cfg["schema"], **auth,
    )
    written = 0
    try:
        cur = conn.cursor()
        for spec, quotes in to_write:
            for key in sorted(quotes):
                q = quotes[key]
                as_of = datetime(q.trade_date.year, q.trade_date.month, q.trade_date.day)
                cur.execute(
                    """
                    MERGE INTO IV_SNAPSHOT t
                    USING (SELECT %s AS KEY, %s AS IV, %s AS SOURCE, %s::TIMESTAMP_NTZ AS AS_OF) s
                    ON t.CANONICAL_KEY = s.KEY
                    WHEN MATCHED AND (t.AS_OF IS NULL OR s.AS_OF >= t.AS_OF) THEN
                        UPDATE SET IV=s.IV, SOURCE=s.SOURCE, AS_OF=s.AS_OF,
                                   UPDATED_AT=CURRENT_TIMESTAMP(), UPDATED_BY=%s
                    WHEN NOT MATCHED THEN
                        INSERT (CANONICAL_KEY, IV, SOURCE, AS_OF, UPDATED_BY)
                        VALUES (s.KEY, s.IV, s.SOURCE, s.AS_OF, %s)
                    """,
                    (reference_key(spec, q.canonical_key), q.iv_pct, q.source_label, as_of,
                     args.updated_by, args.updated_by),
                )
                written += cur.rowcount or 0
        conn.commit()
    finally:
        conn.close()

    total = sum(len(q) for _, q in to_write)
    skipped = total - written
    print(f"\nWrote {written} row(s) to IV_SNAPSHOT"
          + (f"; {skipped} left alone because they already hold newer data." if skipped else "."))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
