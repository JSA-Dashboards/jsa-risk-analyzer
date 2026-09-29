"""One-time seed: IV snapshot, prior settle, contract marks, and the "QST Basic Corn"
default import preset — matching the values already researched/used in the original
HTML tool, so Phase 2's Snowflake-backed book starts from the same place.

Run with: .venv/Scripts/python.exe scripts/seed_reference_data.py
"""
import json
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cryptography.hazmat.primitives import serialization
import snowflake.connector

ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"

# Keys are commodity-prefixed (2-letter product code + canonical key, e.g. "ZC" + "U26")
# so each commodity's reference data has its own namespace in these shared tables -- see
# jsa_risk.pricing.commodities.reference_key. Only corn has real reference data researched
# so far; the other three commodities (ZS/LE/GF) start with none, falling back to the
# app's DEFAULT_CONTRACT_PRICE/DEFAULT_IV placeholders until real data is entered.
IV_SNAPSHOT = {"ZCU26": 25.20, "ZCZ26": 23.43, "ZCN27": 21.50}
IV_SOURCE = "Barchart corn options quotes"

CONTRACT_MARKS = {"ZCU26": 5.15, "ZCZ26": 5.3925, "ZCN27": 5.625}

PRIOR_SETTLE_FUTURES = {"ZCU26": 4.6500, "ZCZ26": 4.8950, "ZCN27": 5.1500}
PRIOR_SETTLE_OPTIONS = [
    ("ZCU26", "call", 5.00, 0.00125),
    ("ZCU26", "put", 4.30, 0.00125),
    ("ZCU26", "call", 4.70, 0.02625),
    ("ZCZ26", "put", 4.50, 0.05625),
    ("ZCZ26", "call", 4.90, 0.21000),
    ("ZCN27", "call", 4.60, 0.66750),
]
PRIOR_SETTLE_AS_OF = "2026-08-17"
PRIOR_SETTLE_SOURCE = "CME Group settlements"

# Matches the real QST "Orders and Positions Summary" export -- this previously carried
# the sample-sheet's placeholder column names ("Symbol"/"Lots"/"Premium"), which never
# matched any real export and silently fell through to auto_map's generic guessing.
QST_BASIC_CORN_MAPPING = {
    "label": "Instrument", "type": "Call/Put", "strike": "Strike", "expiryDate": "Expiration Date",
    "qty": "Qty", "positionDir": "Position", "iv": None, "entry": "Price", "lastTick": "Last Tick",
}


def _load_private_key(sf_cfg) -> bytes | None:
    """RSA private key for Snowflake key-pair auth (the account enforces MFA on
    password sign-ins), as DER bytes; None if not configured (falls back to password).
    Source: private_key_path (.p8 file) or private_key_pem (PEM text)."""
    path = sf_cfg.get("private_key_path")
    pem = sf_cfg.get("private_key_pem")
    if not path and not pem:
        return None
    pem_bytes = open(path, "rb").read() if path else pem.encode()
    key = serialization.load_pem_private_key(pem_bytes, password=None)
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def main() -> int:
    with open(SECRETS_PATH, "rb") as f:
        sf_cfg = tomllib.load(f)["snowflake"]

    kw = {}
    pkey = _load_private_key(sf_cfg)
    if pkey is not None:
        kw["private_key"] = pkey
    else:
        kw["password"] = sf_cfg["password"]
    conn = snowflake.connector.connect(
        account=sf_cfg["account"], user=sf_cfg["user"],
        role=sf_cfg["role"], warehouse=sf_cfg["warehouse"],
        database=sf_cfg["database"], schema=sf_cfg["schema"],
        **kw,
    )
    cur = conn.cursor()

    # One-time migration: earlier seeds wrote bare 3-char keys (e.g. "U26") before
    # reference data became commodity-prefixed. Those rows are now orphaned -- nothing
    # will ever look them up again -- so clear them out rather than leaving stale
    # duplicates alongside the prefixed rows this script writes below.
    for table in ("IV_SNAPSHOT", "CONTRACT_MARKS", "PRIOR_SETTLE_FUTURES", "PRIOR_SETTLE_OPTIONS"):
        cur.execute(f"DELETE FROM {table} WHERE LENGTH(CANONICAL_KEY) = 3")
    print("Cleared orphaned pre-migration (bare 3-char key) reference rows")

    for key, iv in IV_SNAPSHOT.items():
        cur.execute(
            """
            MERGE INTO IV_SNAPSHOT t USING (SELECT %s AS KEY) s ON t.CANONICAL_KEY = s.KEY
            WHEN MATCHED THEN UPDATE SET IV=%s, SOURCE=%s, AS_OF=CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT (CANONICAL_KEY, IV, SOURCE, AS_OF) VALUES (%s, %s, %s, CURRENT_TIMESTAMP())
            """,
            (key, iv, IV_SOURCE, key, iv, IV_SOURCE),
        )
    print(f"Seeded IV_SNAPSHOT: {IV_SNAPSHOT}")

    for key, price in CONTRACT_MARKS.items():
        cur.execute(
            """
            MERGE INTO CONTRACT_MARKS t USING (SELECT %s AS KEY) s ON t.CANONICAL_KEY = s.KEY
            WHEN MATCHED THEN UPDATE SET MARK_PRICE=%s, SOURCE='manual'
            WHEN NOT MATCHED THEN INSERT (CANONICAL_KEY, MARK_PRICE, SOURCE) VALUES (%s, %s, 'manual')
            """,
            (key, price, key, price),
        )
    print(f"Seeded CONTRACT_MARKS: {CONTRACT_MARKS}")

    for key, price in PRIOR_SETTLE_FUTURES.items():
        cur.execute(
            """
            MERGE INTO PRIOR_SETTLE_FUTURES t USING (SELECT %s AS KEY) s ON t.CANONICAL_KEY = s.KEY
            WHEN MATCHED THEN UPDATE SET SETTLE_PRICE=%s, AS_OF=%s, SOURCE=%s
            WHEN NOT MATCHED THEN INSERT (CANONICAL_KEY, SETTLE_PRICE, AS_OF, SOURCE) VALUES (%s, %s, %s, %s)
            """,
            (key, price, PRIOR_SETTLE_AS_OF, PRIOR_SETTLE_SOURCE, key, price, PRIOR_SETTLE_AS_OF, PRIOR_SETTLE_SOURCE),
        )
    print(f"Seeded PRIOR_SETTLE_FUTURES: {PRIOR_SETTLE_FUTURES}")

    for key, opt_type, strike, price in PRIOR_SETTLE_OPTIONS:
        cur.execute(
            """
            MERGE INTO PRIOR_SETTLE_OPTIONS t
            USING (SELECT %s AS KEY, %s AS TYP, %s AS STRK) s
            ON t.CANONICAL_KEY = s.KEY AND t.OPT_TYPE = s.TYP AND t.STRIKE = s.STRK
            WHEN MATCHED THEN UPDATE SET SETTLE_PRICE=%s, AS_OF=%s, SOURCE=%s
            WHEN NOT MATCHED THEN INSERT (CANONICAL_KEY, OPT_TYPE, STRIKE, SETTLE_PRICE, AS_OF, SOURCE)
                              VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (key, opt_type, strike, price, PRIOR_SETTLE_AS_OF, PRIOR_SETTLE_SOURCE,
             key, opt_type, strike, price, PRIOR_SETTLE_AS_OF, PRIOR_SETTLE_SOURCE),
        )
    print(f"Seeded PRIOR_SETTLE_OPTIONS: {len(PRIOR_SETTLE_OPTIONS)} rows")

    cur.execute(
        """
        MERGE INTO IMPORT_PRESETS t USING (SELECT %s AS NAME) s ON t.PRESET_NAME = s.NAME
        WHEN MATCHED THEN UPDATE SET MAPPING_JSON = PARSE_JSON(%s), IS_DEFAULT = TRUE, UPDATED_AT = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT (PRESET_NAME, MAPPING_JSON, IS_DEFAULT) VALUES (%s, PARSE_JSON(%s), TRUE)
        """,
        ("QST Basic Corn", json.dumps(QST_BASIC_CORN_MAPPING), "QST Basic Corn", json.dumps(QST_BASIC_CORN_MAPPING)),
    )
    print('Seeded default preset "QST Basic Corn"')

    conn.commit()
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
