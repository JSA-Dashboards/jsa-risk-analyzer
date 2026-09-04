"""A single cached Snowflake connection, built from `config.get_snowflake_config()`.

Uses the connector directly (rather than `st.connection`'s SnowflakeConnection) so
key-pair auth is unambiguous and matches exactly what `scripts/bootstrap_snowflake.py`
already validated. `st.cache_resource` keeps one connection alive across reruns instead
of reconnecting on every widget interaction.
"""
import pandas as pd
import snowflake.connector
import streamlit as st
from cryptography.hazmat.primitives import serialization
from snowflake.connector.cursor import SnowflakeCursor

from jsa_risk.config import get_snowflake_config


def _load_private_key_der(path: str) -> bytes:
    with open(path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@st.cache_resource(show_spinner=False)
def get_connection() -> snowflake.connector.SnowflakeConnection:
    cfg = get_snowflake_config()
    return snowflake.connector.connect(
        account=cfg.account,
        user=cfg.user,
        private_key=_load_private_key_der(cfg.private_key_path),
        role=cfg.role,
        warehouse=cfg.warehouse,
        database=cfg.database,
        schema=cfg.schema,
    )


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    cur: SnowflakeCursor = get_connection().cursor()
    try:
        cur.execute(sql, params)
        return cur.fetch_pandas_all()
    finally:
        cur.close()


def execute(sql: str, params: tuple = ()) -> None:
    cur = get_connection().cursor()
    try:
        cur.execute(sql, params)
    finally:
        cur.close()


def executemany(sql: str, seq_of_params: list) -> None:
    if not seq_of_params:
        return
    cur = get_connection().cursor()
    try:
        cur.executemany(sql, seq_of_params)
    finally:
        cur.close()
