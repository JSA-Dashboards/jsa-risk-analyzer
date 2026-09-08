"""The only module that reads `st.secrets` — everything else asks these functions for
config, so a missing/misconfigured secret surfaces as one friendly message instead of a
raw KeyError reaching the UI."""
from dataclasses import dataclass
from typing import Optional

import streamlit as st


class ConfigError(RuntimeError):
    """A required secret/config block is missing. Message is safe to show in the UI."""


@dataclass(frozen=True)
class SnowflakeConfig:
    account: str
    user: str
    role: str
    warehouse: str
    database: str
    schema: str
    private_key_path: Optional[str] = None
    private_key_pem: Optional[str] = None


@dataclass(frozen=True)
class MassiveConfig:
    api_key: str
    base_url: str


@dataclass(frozen=True)
class CmeGreeksConfig:
    api_id: str
    password: str
    base_url: str
    token_url: str


def _section(name: str, friendly_name: str) -> dict:
    if name not in st.secrets:
        raise ConfigError(
            f"{friendly_name} isn't configured yet — add a [{name}] block to "
            f".streamlit/secrets.toml (see secrets.toml.example)."
        )
    return st.secrets[name]


def get_snowflake_config() -> SnowflakeConfig:
    s = _section("snowflake", "Snowflake")
    private_key_path = s.get("private_key_path")
    private_key_pem = s.get("private_key_pem")
    if not private_key_path and not private_key_pem:
        raise ConfigError(
            "Snowflake key-pair auth needs either private_key_path (a local file — dev "
            "only) or private_key_pem (the key's contents — required on Streamlit Cloud, "
            "which has no persistent filesystem) in the [snowflake] secrets block."
        )
    return SnowflakeConfig(
        account=s["account"], user=s["user"], role=s["role"], warehouse=s["warehouse"],
        database=s["database"], schema=s["schema"],
        private_key_path=private_key_path, private_key_pem=private_key_pem,
    )


def get_massive_config() -> Optional[MassiveConfig]:
    """Returns None (not an error) when unconfigured — the Massive fetch button just
    disables itself; it's a convenience feature, not a hard dependency."""
    if "massive" not in st.secrets:
        return None
    s = st.secrets["massive"]
    return MassiveConfig(api_key=s["api_key"], base_url=s.get("base_url", "https://api.massive.com"))


def get_cme_config() -> Optional[CmeGreeksConfig]:
    """Returns None (not an error) when unconfigured — CME Greeks are best-effort/optional
    per the plan (corn's entitlement on CME's product list isn't yet confirmed)."""
    if "cme_greeks" not in st.secrets:
        return None
    s = st.secrets["cme_greeks"]
    return CmeGreeksConfig(
        api_id=s["api_id"], password=s["password"],
        base_url=s.get("base_url", "https://markets.api.cmegroup.com/greeks/v1"),
        token_url=s.get("token_url", "https://auth.cmegroup.com/as/token.oauth2"),
    )
