"""One-time setup script: test the Snowflake key-pair connection and create the
RISK_ANALYZER schema + tables described in the migration plan. Reads connection
details straight out of .streamlit/secrets.toml so it uses the exact same config the
Streamlit app will use.

Run with: .venv/Scripts/python.exe scripts/bootstrap_snowflake.py
"""
import sys
import tomllib
from pathlib import Path

from cryptography.hazmat.primitives import serialization
import snowflake.connector

ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"

DDL_STATEMENTS = [
    "CREATE SCHEMA IF NOT EXISTS JSA.RISK_ANALYZER",
    """
    CREATE TABLE IF NOT EXISTS JSA.RISK_ANALYZER.IMPORT_BATCHES (
        IMPORT_BATCH_ID NUMBER AUTOINCREMENT PRIMARY KEY,
        IMPORTED_AT     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
        IMPORTED_BY     VARCHAR(128),
        SOURCE_FILENAME VARCHAR(256),
        MAPPING_JSON    VARIANT,
        ROW_COUNT       NUMBER,
        NOTE            VARCHAR(1024)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS JSA.RISK_ANALYZER.POSITIONS (
        POSITION_ID     NUMBER AUTOINCREMENT PRIMARY KEY,
        LABEL           VARCHAR(32)  NOT NULL,
        TYPE            VARCHAR(8)   NOT NULL,
        STRIKE          NUMBER(10,4),
        EXPIRY_DATE     DATE,
        QTY             NUMBER(10,0) NOT NULL,
        IV              NUMBER(8,4),
        IV_ESTIMATED    BOOLEAN DEFAULT FALSE,
        ENTRY           NUMBER(10,4) NOT NULL,
        LAST_TICK       NUMBER(10,4),
        IMPORT_MARK     NUMBER(10,4),
        IMPORT_BATCH_ID NUMBER REFERENCES JSA.RISK_ANALYZER.IMPORT_BATCHES(IMPORT_BATCH_ID),
        CREATED_AT      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
        UPDATED_AT      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
        UPDATED_BY      VARCHAR(128)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS JSA.RISK_ANALYZER.POSITION_HISTORY (
        HISTORY_ID       NUMBER AUTOINCREMENT PRIMARY KEY,
        IMPORT_BATCH_ID  NUMBER REFERENCES JSA.RISK_ANALYZER.IMPORT_BATCHES(IMPORT_BATCH_ID),
        SNAPSHOT_AT      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
        POSITIONS_JSON   VARIANT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS JSA.RISK_ANALYZER.IMPORT_PRESETS (
        PRESET_NAME   VARCHAR(128) PRIMARY KEY,
        MAPPING_JSON  VARIANT NOT NULL,
        IS_DEFAULT    BOOLEAN DEFAULT FALSE,
        CREATED_AT    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
        CREATED_BY    VARCHAR(128),
        UPDATED_AT    TIMESTAMP_NTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS JSA.RISK_ANALYZER.IMPORT_LAST_USED_MAPPING (
        ID            NUMBER PRIMARY KEY DEFAULT 1,
        MAPPING_JSON  VARIANT,
        UPDATED_AT    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS JSA.RISK_ANALYZER.IV_SNAPSHOT (
        CANONICAL_KEY VARCHAR(8) PRIMARY KEY,
        IV            NUMBER(8,4) NOT NULL,
        AS_OF         TIMESTAMP_NTZ,
        SOURCE        VARCHAR(256),
        UPDATED_AT    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
        UPDATED_BY    VARCHAR(128)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS JSA.RISK_ANALYZER.PRIOR_SETTLE_FUTURES (
        CANONICAL_KEY VARCHAR(8) PRIMARY KEY,
        SETTLE_PRICE  NUMBER(10,4),
        AS_OF         DATE,
        SOURCE        VARCHAR(256)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS JSA.RISK_ANALYZER.PRIOR_SETTLE_OPTIONS (
        CANONICAL_KEY VARCHAR(8),
        OPT_TYPE      VARCHAR(8),
        STRIKE        NUMBER(10,4),
        SETTLE_PRICE  NUMBER(10,4),
        AS_OF         DATE,
        SOURCE        VARCHAR(256),
        PRIMARY KEY (CANONICAL_KEY, OPT_TYPE, STRIKE)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS JSA.RISK_ANALYZER.CONTRACT_MARKS (
        CANONICAL_KEY VARCHAR(8) PRIMARY KEY,
        MARK_PRICE    NUMBER(10,4),
        SOURCE        VARCHAR(32),
        UPDATED_AT    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS JSA.RISK_ANALYZER.EXTERNAL_FETCH_LOG (
        FETCH_ID      NUMBER AUTOINCREMENT PRIMARY KEY,
        PROVIDER      VARCHAR(16),
        ENDPOINT      VARCHAR(256),
        REQUESTED_AT  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
        SUCCESS       BOOLEAN,
        HTTP_STATUS   NUMBER,
        RETRY_COUNT   NUMBER DEFAULT 0,
        ERROR_MESSAGE VARCHAR(2048),
        REQUESTED_BY  VARCHAR(128)
    )
    """,
]


def load_private_key(path: str) -> bytes:
    with open(path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def main() -> int:
    with open(SECRETS_PATH, "rb") as f:
        secrets = tomllib.load(f)
    sf = secrets["snowflake"]

    conn = snowflake.connector.connect(
        account=sf["account"],
        user=sf["user"],
        private_key=load_private_key(sf["private_key_path"]),
        role=sf["role"],
        warehouse=sf["warehouse"],
        database=sf["database"],
    )
    print("Connected OK.")

    cur = conn.cursor()
    for stmt in DDL_STATEMENTS:
        cur.execute(stmt)
        print(f"OK: {stmt.strip().splitlines()[0][:80]}")

    cur.execute("SHOW TABLES IN SCHEMA JSA.RISK_ANALYZER")
    tables = [row[1] for row in cur.fetchall()]
    print(f"\nTables now in JSA.RISK_ANALYZER: {tables}")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
