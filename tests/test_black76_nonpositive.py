from jsa_risk.pricing.black76 import black76


def test_zero_forward_does_not_raise():
    r = black76(0.0, 4.5, 0.25, 20.0, True)
    assert r.price == 0.0 and r.gamma == 0.0


def test_zero_strike_does_not_raise():
    r = black76(4.5, 0.0, 0.25, 20.0, False)
    assert r.price == 0.0


def test_normal_inputs_unchanged():
    assert black76(4.5, 4.5, 0.25, 20.0, True).price > 0
