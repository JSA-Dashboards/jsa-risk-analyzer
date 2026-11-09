from unittest.mock import patch

from jsa_risk.data import audit_repo


def test_a_failed_audit_write_never_breaks_the_fetch():
    with patch.object(audit_repo.sf, "execute", side_effect=RuntimeError("Insufficient privileges")):
        audit_repo.log_fetch("massive", "/futures/v1/snapshot", success=True, http_status=200)   # must not raise


def test_a_normal_audit_write_still_happens():
    with patch.object(audit_repo.sf, "execute") as ex:
        audit_repo.log_fetch("massive", "/futures/v1/snapshot", success=False, error_message="boom")
    ex.assert_called_once()
