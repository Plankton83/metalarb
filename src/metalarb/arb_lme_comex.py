"""Leg 1: LME -> COMEX landed-cost arbitrage (the tariff arb).

Economic question: is it profitable to buy copper at the LME price, take
physical delivery ex-warehouse outside the US, ship it to a CME-deliverable
US warehouse, and sell at the COMEX price?

The answer is scenario-dependent because the dominant cost is the import
duty. The reverse view (exiting US inventory) is computed alongside to show
the one-way door: once duty is paid it is sunk, so metal that entered the US
cannot economically leave when the spread narrows.

Note on the waterfall: the physical premium appears as an explicit step —
without it the decomposition from spread to net margin would not reconcile,
since the margin is measured against the LME screen price but metal is
acquired at LME + premium.
"""

from __future__ import annotations

from metalarb.costs import acquisition_cost, duty_cost, financing_cost, insurance_cost
from metalarb.models import (
    Assumptions,
    ComexArbInputs,
    ComexArbResult,
    ComexExitResult,
    Scenario,
)


def compute_comex_arb(
    inputs: ComexArbInputs,
    assumptions: Assumptions,
    scenario: Scenario,
    open_threshold_usd_mt: float = 0.0,
) -> ComexArbResult:
    """Compute landed cost, margin, breakeven and exit economics for one scenario.

    Landed cost (USD/mt) =
        (LME price + physical premium)   metal acquisition
        + freight                        sea freight to US Gulf
        + insurance                      % of cargo value
        + financing                      cost of carry over transit + customs
        + warehouse-in charges           US warehouse handling
        + duty                           duty_rate x customs value

    Customs value is simplified to the acquisition cost (LME + premium);
    see :func:`metalarb.costs.duty_cost`.
    """
    leg = assumptions.lme_comex
    cargo_value = acquisition_cost(inputs.lme_price_usd_mt, leg.physical_premium_usd_mt)
    insurance = insurance_cost(cargo_value, leg.insurance_rate)
    financing = financing_cost(cargo_value, assumptions.market.funding_rate, leg.total_days)
    duty = duty_cost(cargo_value, scenario.duty_rate)

    landed_cost = (
        cargo_value
        + leg.freight_usd_mt
        + insurance
        + financing
        + leg.warehouse_in_charges_usd_mt
        + duty
    )
    gross_margin = inputs.comex_price_usd_mt - landed_cost
    # The spread (COMEX - LME) at which the margin is exactly zero: every
    # dollar of cost above the LME price must be recovered by the spread.
    breakeven_spread = landed_cost - inputs.lme_price_usd_mt

    waterfall = {
        "spread": inputs.spread_usd_mt,
        "physical_premium": -leg.physical_premium_usd_mt,
        "freight": -leg.freight_usd_mt,
        "insurance": -insurance,
        "financing": -financing,
        "warehouse_in_charges": -leg.warehouse_in_charges_usd_mt,
        "duty": -duty,
        "net_margin": gross_margin,
    }

    return ComexArbResult(
        scenario_name=scenario.name,
        duty_rate=scenario.duty_rate,
        lme_price_usd_mt=inputs.lme_price_usd_mt,
        comex_price_usd_mt=inputs.comex_price_usd_mt,
        landed_cost_usd_mt=landed_cost,
        gross_margin_usd_mt=gross_margin,
        breakeven_spread_usd_mt=breakeven_spread,
        is_open=gross_margin > open_threshold_usd_mt,
        waterfall=waterfall,
        exit=compute_exit_economics(inputs, assumptions),
    )


def compute_exit_economics(
    inputs: ComexArbInputs,
    assumptions: Assumptions,
) -> ComexExitResult:
    """Economics of moving metal from a US warehouse back onto LME warrant.

    The exit mirrors the inbound leg's logistics costs — outbound freight,
    insurance and financing over the same transit window, at the same rates —
    but with three asymmetries that create the one-way door:

    - the metal is bought (valued) at the COMEX price, which is exactly what
      made the inbound trade attractive;
    - re-delivery against LME warrants earns the LME price *flat* — the
      physical premium is what ex-warehouse buyers pay, not what warrant
      deliverers receive;
    - the import duty paid on the way in is not refunded on export.

    So even at a zero spread the exit loses the full logistics round-trip,
    and the duty already paid is stranded value.
    """
    leg = assumptions.lme_comex
    cargo_value = inputs.comex_price_usd_mt
    insurance = insurance_cost(cargo_value, leg.insurance_rate)
    financing = financing_cost(cargo_value, assumptions.market.funding_rate, leg.total_days)

    exit_cost = cargo_value + leg.exit_freight_usd_mt + insurance + financing
    exit_margin = inputs.lme_price_usd_mt - exit_cost

    waterfall = {
        "reverse_spread": inputs.lme_price_usd_mt - inputs.comex_price_usd_mt,
        "exit_freight": -leg.exit_freight_usd_mt,
        "insurance": -insurance,
        "financing": -financing,
        "net_margin": exit_margin,
    }

    return ComexExitResult(
        exit_cost_usd_mt=exit_cost,
        exit_margin_usd_mt=exit_margin,
        waterfall=waterfall,
    )
