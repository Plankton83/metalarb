"""Unit and FX conversion tests, including round-trip properties."""

from __future__ import annotations

import pytest

from metalarb.conversions import (
    LBS_PER_METRIC_TONNE,
    cents_per_lb_to_usd_per_mt,
    cny_per_mt_to_usd_per_mt,
    usd_per_mt_to_cents_per_lb,
    usd_per_mt_to_cny_per_mt,
)


def test_cents_per_lb_known_value():
    """480 cents/lb = 4.80 USD/lb; 4.80 * 2204.62 = 10,582.176 USD/mt."""
    assert cents_per_lb_to_usd_per_mt(480) == pytest.approx(10_582.176)


def test_usd_per_mt_to_cents_known_value():
    """Inverse of the above: 10,582.176 USD/mt back to 480 cents/lb."""
    assert usd_per_mt_to_cents_per_lb(10_582.176) == pytest.approx(480)


def test_cny_conversion_known_value():
    """71,000 CNY/mt at USDCNY 7.10 = 10,000 USD/mt, and back."""
    assert cny_per_mt_to_usd_per_mt(71_000, 7.10) == pytest.approx(10_000)
    assert usd_per_mt_to_cny_per_mt(10_000, 7.10) == pytest.approx(71_000)


@pytest.mark.parametrize("cents", [50.0, 300.0, 480.0, 655.25, 1_000.0])
def test_cents_round_trip(cents: float):
    """cents/lb -> USD/mt -> cents/lb is the identity (float tolerance)."""
    assert usd_per_mt_to_cents_per_lb(cents_per_lb_to_usd_per_mt(cents)) == pytest.approx(cents)


@pytest.mark.parametrize("usd", [1_000.0, 9_500.0, 12_345.67])
@pytest.mark.parametrize("fx", [6.5, 7.10, 7.35])
def test_cny_round_trip(usd: float, fx: float):
    """USD/mt -> CNY/mt -> USD/mt is the identity for any positive FX rate."""
    assert cny_per_mt_to_usd_per_mt(usd_per_mt_to_cny_per_mt(usd, fx), fx) == pytest.approx(usd)


def test_lbs_per_tonne_constant():
    """The COMEX contract conversion constant from the spec."""
    assert LBS_PER_METRIC_TONNE == 2204.62


@pytest.mark.parametrize("bad", [0.0, -1.0, -480.0])
def test_zero_or_negative_prices_rejected(bad: float):
    with pytest.raises(ValueError):
        cents_per_lb_to_usd_per_mt(bad)
    with pytest.raises(ValueError):
        usd_per_mt_to_cents_per_lb(bad)


@pytest.mark.parametrize("bad_fx", [0.0, -7.1])
def test_bad_fx_rejected(bad_fx: float):
    with pytest.raises(ValueError):
        cny_per_mt_to_usd_per_mt(71_000, bad_fx)
    with pytest.raises(ValueError):
        usd_per_mt_to_cny_per_mt(10_000, bad_fx)
