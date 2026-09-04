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

IV_SNAPSHOT = {"U26": 25.20, "Z26": 23.43, "N27": 21.50}
IV_SOURCE = "Barchart corn options quotes"

CONTRACT_MARKS = {"U26": 5.15, "Z26": 5.3925, "N27": 5.625}

PRIOR_SETTLE_FUTURES = {"U26": 4.6500, "Z26": 4.8950, "N27": 5.1500}
PRIOR_SETTLE_OPTIONS = [
    ("U26", "call", 5.00, 0.00125),
    ("U26", "put", 4.30, 0.00125),
    ("U26", "call", 4.70, 0.02625),
    ("Z26", "put", 4.50, 0.05625),
    ("Z26", "call", 4.90, 0.21000),
    ("N27", "call", 4.60, 0.66750),
]
PRIOR_SETTLE_AS_OF = "2026-08-17"
PRIOR_SETTLE_SOURCE = "CME Group settlements"

QST_BASIC_CORN_MAPPING = {
    "label": "Symbol", "type": "Type", "strike": "Strike", "expiryDate": "Expiration",
    "qty": "Lots", "positionDir": None, "iv": None, "entry": "Premium", "lastTick": "Last Tick",
}


def load_private_key_der(path: str) -> bytes:
    with open(path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def main() -> int:
    with open(SECRETS_PATH, "rb") as f:
        sf_cfg = tomllib.load(f)["snowflake"]

    conn = snowflake.connector.connect(
        account=sf_cfg["account"], user=sf_cfg["user"],
        private_key=load_private_key_der(sf_cfg["private_key_path"]),
        role=sf_cfg["role"], warehouse=sf_cfg["warehouse"],
        database=sf_cfg["database"], schema=sf_cfg["schema"],
    )
    cur = conn.cursor()

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
