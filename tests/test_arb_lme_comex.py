"""Leg 1 (LME -> COMEX) tests: known values, waterfall reconciliation, exit economics."""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from metalarb.arb_lme_comex import compute_comex_arb, compute_exit_economics
from metalarb.models import ComexArbInputs, Scenario


@pytest.fixture
def inputs() -> ComexArbInputs:
    # COMEX 480 cents/lb = 10,582.176 USD/mt (converted at the boundary).
    return ComexArbInputs(lme_price_usd_mt=9_500, comex_price_usd_mt=10_582.176)


def test_known_value_phased_2027(inputs, assumptions):
    """Full hand calculation, scenario phased_2027 (duty 15%):

    acquisition = 9,500 + 250                    =  9,750.000
    freight                                      =    120.000
    insurance   = 0.003 * 9,750                  =     29.250
    financing   = 9,750 * 0.06 * 35/360          =     56.875
    warehouse                                    =     25.000
    duty        = 0.15 * 9,750                   =  1,462.500
    landed cost                                  = 11,443.625

    margin      = 10,582.176 - 11,443.625        =   -861.449
    breakeven   = 11,443.625 - 9,500             =  1,943.625
    """
    result = compute_comex_arb(inputs, assumptions, Scenario("phased_2027", 0.15))
    assert result.landed_cost_usd_mt == pytest.approx(11_443.625)
    assert result.gross_margin_usd_mt == pytest.approx(-861.449)
    assert result.breakeven_spread_usd_mt == pytest.approx(1_943.625)
    assert result.is_open is False


def test_known_value_no_tariff(inputs, assumptions):
    """Same trade with zero duty: landed = 9,981.125, margin = +601.051 -> open.

    landed = 9,750 + 120 + 29.25 + 56.875 + 25 = 9,981.125
    margin = 10,582.176 - 9,981.125 = 601.051
    """
    result = compute_comex_arb(inputs, assumptions, Scenario("no_tariff", 0.0))
    assert result.landed_cost_usd_mt == pytest.approx(9_981.125)
    assert result.gross_margin_usd_mt == pytest.approx(601.051)
    assert result.is_open is True


def test_waterfall_reconciles_to_margin(inputs, assumptions):
    """Sum of all waterfall steps before net_margin equals net_margin exactly."""
    result = compute_comex_arb(inputs, assumptions, Scenario("phased_2027", 0.15))
    steps = [v for k, v in result.waterfall.items() if k != "net_margin"]
    assert math.fsum(steps) == pytest.approx(result.waterfall["net_margin"])
    assert result.waterfall["net_margin"] == pytest.approx(result.gross_margin_usd_mt)


def test_breakeven_inversion_property(inputs, assumptions):
    """margin == actual spread - breakeven spread, by construction.

    The breakeven spread is the landed cost above LME; the margin is what the
    actual spread pays beyond that.
    """
    for duty in (0.0, 0.15, 0.30, 0.50):
        result = compute_comex_arb(inputs, assumptions, Scenario("s", duty))
        assert result.gross_margin_usd_mt == pytest.approx(
            inputs.spread_usd_mt - result.breakeven_spread_usd_mt
        )


def test_margin_monotonically_decreasing_in_duty(inputs, assumptions):
    """Property: every extra point of duty strictly reduces the margin."""
    margins = [
        compute_comex_arb(inputs, assumptions, Scenario("s", duty)).gross_margin_usd_mt
        for duty in (0.0, 0.05, 0.15, 0.30, 0.50)
    ]
    assert all(a > b for a, b in pairwise(margins))


def test_open_threshold(inputs, assumptions):
    """A margin below the required threshold keeps the verdict closed."""
    result = compute_comex_arb(
        inputs, assumptions, Scenario("no_tariff", 0.0), open_threshold_usd_mt=700
    )
    assert result.gross_margin_usd_mt == pytest.approx(601.051)
    assert result.is_open is False


def test_exit_economics_known_value(inputs, assumptions):
    """Hand calculation of the one-way-door exit (US -> LME):

    cargo value = COMEX price                    = 10,582.176
    exit freight                                 =    120.000
    insurance   = 0.003 * 10,582.176             =     31.746528
    financing   = 10,582.176 * 0.06 * 35/360     =     61.729360
    exit cost                                    = 10,795.651888

    Revenue is the LME price FLAT (no premium on warrant delivery):
    exit margin = 9,500 - 10,795.651888          = -1,295.651888
    """
    result = compute_exit_economics(inputs, assumptions)
    assert result.exit_cost_usd_mt == pytest.approx(10_795.651888)
    assert result.exit_margin_usd_mt == pytest.approx(-1_295.651888)


def test_exit_waterfall_reconciles(inputs, assumptions):
    result = compute_exit_economics(inputs, assumptions)
    steps = [v for k, v in result.waterfall.items() if k != "net_margin"]
    assert math.fsum(steps) == pytest.approx(result.waterfall["net_margin"])


def test_one_way_door(inputs, assumptions):
    """Even when the inbound arb is open (no tariff), the exit loses money:
    the round trip pays logistics twice and earns no premium on the way out.
    This is the trapped-metal mechanic the tool must demonstrate.
    """
    inbound = compute_comex_arb(inputs, assumptions, Scenario("no_tariff", 0.0))
    assert inbound.is_open is True
    assert inbound.exit.exit_margin_usd_mt < 0


def test_negative_spread_handled(assumptions):
    """COMEX below LME is a valid input; the margin just goes deeply negative."""
    inputs = ComexArbInputs(lme_price_usd_mt=9_500, comex_price_usd_mt=9_000)
    result = compute_comex_arb(inputs, assumptions, Scenario("no_tariff", 0.0))
    assert result.gross_margin_usd_mt < 0
    assert result.is_open is False


@pytest.mark.parametrize(
    "lme,comex", [(0, 10_000), (-1, 10_000), (9_500, 0), (9_500, -5)]
)
def test_zero_or_negative_prices_rejected(lme: float, comex: float):
    with pytest.raises(ValueError):
        ComexArbInputs(lme_price_usd_mt=lme, comex_price_usd_mt=comex)
