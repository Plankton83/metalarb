"""Leg 2 (LME -> SHFE) tests: known values, waterfall reconciliation, validation."""

from __future__ import annotations

import math

import pytest

from metalarb.arb_lme_shfe import compute_shfe_arb
from metalarb.models import ShfeArbInputs


@pytest.fixture
def inputs() -> ShfeArbInputs:
    return ShfeArbInputs(lme_price_usd_mt=9_500, shfe_price_cny_mt=78_000, usdcny=7.10)


def test_known_value(inputs, assumptions):
    """Full hand calculation of the import parity:

    CIF value   = (9,500 + 100)                =  9,600 USD/mt
    CIF in CNY  = 9,600 * 7.10                 = 68,160 CNY/mt
    VAT gross-up= 68,160 * 1.13                = 77,020.80 CNY/mt
    import cost = 77,020.80 + 100 admin        = 77,120.80 CNY/mt

    margin CNY  = 78,000 - 77,120.80           =    879.20 CNY/mt
    margin USD  = 879.20 / 7.10                =    123.830986 USD/mt
    """
    result = compute_shfe_arb(inputs, assumptions)
    assert result.import_cost_cny_mt == pytest.approx(77_120.80)
    assert result.arb_margin_cny_mt == pytest.approx(879.20)
    assert result.arb_margin_usd_mt == pytest.approx(879.20 / 7.10)
    assert result.breakeven_shfe_price_cny_mt == pytest.approx(77_120.80)
    assert result.is_open is True


def test_closed_window(inputs, assumptions):
    """A cheaper SHFE closes the window: margin negative, verdict closed."""
    closed = ShfeArbInputs(lme_price_usd_mt=9_500, shfe_price_cny_mt=76_000, usdcny=7.10)
    result = compute_shfe_arb(closed, assumptions)
    assert result.arb_margin_cny_mt == pytest.approx(76_000 - 77_120.80)
    assert result.is_open is False


def test_waterfall_reconciles_to_margin(inputs, assumptions):
    """Sum of waterfall steps before net_margin equals net_margin exactly.

    Decomposition: (SHFE - LME_cny) - CIF premium_cny - VAT on CIF value
    - admin = margin.
    """
    result = compute_shfe_arb(inputs, assumptions)
    steps = [v for k, v in result.waterfall.items() if k != "net_margin"]
    assert math.fsum(steps) == pytest.approx(result.waterfall["net_margin"])
    assert result.waterfall["net_margin"] == pytest.approx(result.arb_margin_cny_mt)


def test_waterfall_components_known_values(inputs, assumptions):
    """spread = 78,000 - 67,450 = 10,550; VAT = 0.13 * 68,160 = 8,860.80."""
    result = compute_shfe_arb(inputs, assumptions)
    assert result.waterfall["spread_cny"] == pytest.approx(10_550)
    assert result.waterfall["cif_premium"] == pytest.approx(-710)
    assert result.waterfall["vat"] == pytest.approx(-8_860.80)
    assert result.waterfall["admin_charge"] == pytest.approx(-100)


def test_margin_decreasing_in_vat(inputs, assumptions):
    """Property: a higher VAT rate strictly reduces the import margin."""
    from dataclasses import replace

    margins = []
    for vat in (0.09, 0.13, 0.17):
        modified = replace(
            assumptions, lme_shfe=replace(assumptions.lme_shfe, vat_rate=vat)
        )
        margins.append(compute_shfe_arb(inputs, modified).arb_margin_cny_mt)
    assert margins[0] > margins[1] > margins[2]


def test_breakeven_is_import_cost(inputs, assumptions):
    """At SHFE == import cost, the margin is exactly zero."""
    result = compute_shfe_arb(inputs, assumptions)
    at_breakeven = ShfeArbInputs(
        lme_price_usd_mt=9_500,
        shfe_price_cny_mt=result.breakeven_shfe_price_cny_mt,
        usdcny=7.10,
    )
    assert compute_shfe_arb(at_breakeven, assumptions).arb_margin_cny_mt == pytest.approx(
        0, abs=1e-9
    )


@pytest.mark.parametrize(
    "lme,shfe,fx",
    [
        (0, 78_000, 7.10),
        (9_500, 0, 7.10),
        (9_500, 78_000, 0),
        (-9_500, 78_000, 7.10),
        (9_500, 78_000, -7.10),
    ],
)
def test_zero_or_negative_inputs_rejected(lme: float, shfe: float, fx: float):
    with pytest.raises(ValueError):
        ShfeArbInputs(lme_price_usd_mt=lme, shfe_price_cny_mt=shfe, usdcny=fx)
