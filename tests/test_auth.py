from unittest.mock import patch

from jsa_risk import config
from jsa_risk.auth import password_matches


def test_matches_only_the_exact_password():
    assert password_matches("s3cret", "s3cret")
    assert not password_matches("s3cre", "s3cret")
    assert not password_matches("S3CRET", "s3cret")


def test_an_unset_password_matches_nothing_not_even_a_blank_entry():
    assert not password_matches("", None)
    assert not password_matches("", "")
    assert not password_matches("anything", None)


def test_password_is_read_from_the_app_block_or_the_root_key():
    with patch.object(config.st, "secrets", {"app": {"password": "from-block"}}):
        assert config.get_app_password() == "from-block"
    with patch.object(config.st, "secrets", {"APP_PASSWORD": "from-root"}):
        assert config.get_app_password() == "from-root"


def test_no_password_configured_gives_none():
    with patch.object(config.st, "secrets", {}):
        assert config.get_app_password() is None
    with patch.object(config.st, "secrets", {"app": {}}):
        assert config.get_app_password() is None
