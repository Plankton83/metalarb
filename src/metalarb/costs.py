"""Cost component functions shared by both arbitrage legs.

Each function is a pure map from economic parameters to a USD/mt (or CNY/mt)
cost. Keeping components separate — rather than one landed-cost formula —
is what makes the waterfall decomposition and the scenario engine possible.
"""

from __future__ import annotations

# Money-market convention for short-dated USD funding (ACT/360).
DAY_COUNT_BASE = 360


def acquisition_cost(lme_price_usd_mt: float, physical_premium_usd_mt: float) -> float:
    """All-in cost of securing physical metal ex-warehouse.

    The LME screen price buys a warrant, not metal in hand at a convenient
    location: obtaining physical units of a specific brand at a specific
    warehouse costs an ex-warehouse premium on top.
    """
    return lme_price_usd_mt + physical_premium_usd_mt


def insurance_cost(cargo_value_usd_mt: float, insurance_rate: float) -> float:
    """Marine cargo insurance, charged as a fraction of insured value."""
    return insurance_rate * cargo_value_usd_mt


def financing_cost(
    cargo_value_usd_mt: float,
    annual_rate: float,
    days: float,
    day_count_base: int = DAY_COUNT_BASE,
) -> float:
    """Cost of carry: funding the cargo value over the transit window.

    The buyer pays at loading and monetizes on arrival, so the cargo value is
    financed at an annualized rate for the transit + clearance days, accrued
    on the money-market ACT/360 convention.
    """
    return cargo_value_usd_mt * annual_rate * days / day_count_base


def duty_cost(customs_value_usd_mt: float, duty_rate: float) -> float:
    """Ad-valorem import duty on the declared customs value.

    Simplification (documented): customs value is taken as the metal
    acquisition cost (LME price + physical premium). Real customs valuation
    can differ (transaction value, includable freight/insurance depending on
    incoterms and jurisdiction).
    """
    return duty_rate * customs_value_usd_mt
