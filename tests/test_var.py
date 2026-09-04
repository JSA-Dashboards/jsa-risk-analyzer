import pytest

from jsa_risk.pricing.var import Z_95, value_at_risk


def test_var_matches_the_documented_formula():
    assert value_at_risk(net_delta_d=100_000) == pytest.approx(1.645 * 100_000 * 0.016)


def test_var_is_sign_insensitive():
    assert value_at_risk(net_delta_d=-100_000) == value_at_risk(net_delta_d=100_000)


def test_var_zero_exposure_is_zero_risk():
    assert value_at_risk(net_delta_d=0) == 0


def test_var_respects_custom_vol_and_z():
    assert value_at_risk(net_delta_d=50_000, daily_vol=0.02, z=2.0) == pytest.approx(2.0 * 50_000 * 0.02)


def test_default_z_is_95_percent_one_sided():
    assert Z_95 == 1.645
