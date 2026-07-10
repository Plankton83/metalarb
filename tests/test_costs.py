"""Cost component tests with hand-computed expected values."""

from __future__ import annotations

import pytest

from metalarb.costs import acquisition_cost, duty_cost, financing_cost, insurance_cost


def test_acquisition_cost():
    """9,500 LME + 250 premium = 9,750 USD/mt all-in metal cost."""
    assert acquisition_cost(9_500, 250) == pytest.approx(9_750)


def test_insurance_cost():
    """0.3% of a 9,750 USD/mt cargo = 29.25 USD/mt."""
    assert insurance_cost(9_750, 0.003) == pytest.approx(29.25)


def test_financing_cost():
    """Hand calculation (ACT/360):

    9,750 * (0.045 + 0.015) * 35 / 360
      = 9,750 * 0.06 * 0.097222...
      = 585 * 35 / 360
      = 56.875 USD/mt
    """
    assert financing_cost(9_750, 0.06, 35) == pytest.approx(56.875)


def test_financing_cost_zero_days():
    """No transit, no carry."""
    assert financing_cost(9_750, 0.06, 0) == 0


def test_duty_cost():
    """15% duty on a 9,750 USD/mt customs value = 1,462.50 USD/mt."""
    assert duty_cost(9_750, 0.15) == pytest.approx(1_462.50)


def test_duty_cost_zero_rate():
    assert duty_cost(9_750, 0.0) == 0


@pytest.mark.parametrize("rate_a,rate_b", [(0.0, 0.15), (0.15, 0.30), (0.30, 0.50)])
def test_duty_monotonic_in_rate(rate_a: float, rate_b: float):
    """Duty (and hence landed cost) is monotonically increasing in duty_rate."""
    assert duty_cost(9_750, rate_a) < duty_cost(9_750, rate_b)
