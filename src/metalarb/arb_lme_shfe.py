"""Leg 2: LME -> SHFE import-parity arbitrage.

Economic question: can copper be imported into China below the SHFE price?

Import parity (per the publicly documented LME/SHFE arb structure):

    import_cost_cny_mt = (lme_price + cif_premium) * usdcny * (1 + vat_rate)
                         + admin_charge_cny
    arb_margin_cny_mt  = shfe_price - import_cost_cny_mt

VAT applies to the full CIF value because Chinese import VAT is levied on
the duty-paid customs value; SHFE prices are VAT-inclusive, so comparing a
VAT-grossed import cost against the SHFE screen is like-for-like.
A positive margin means the import window is open: buy LME, sell SHFE.
"""

from __future__ import annotations

from metalarb.conversions import cny_per_mt_to_usd_per_mt, usd_per_mt_to_cny_per_mt
from metalarb.models import Assumptions, ShfeArbInputs, ShfeArbResult


def compute_shfe_arb(
    inputs: ShfeArbInputs,
    assumptions: Assumptions,
    open_threshold_cny_mt: float = 0.0,
) -> ShfeArbResult:
    """Compute the China import-parity cost, margin and waterfall (CNY/mt).

    The waterfall starts from the raw SHFE-vs-LME spread in CNY and deducts
    the CIF premium, the VAT gross-up on the full CIF value, and the flat
    administrative charge, reconciling exactly to the net margin.
    """
    leg = assumptions.lme_shfe
    cif_value_usd = inputs.lme_price_usd_mt + leg.cif_premium_usd_mt
    cif_value_cny = usd_per_mt_to_cny_per_mt(cif_value_usd, inputs.usdcny)

    import_cost_cny = cif_value_cny * (1 + leg.vat_rate) + leg.admin_charge_cny_mt
    margin_cny = inputs.shfe_price_cny_mt - import_cost_cny
    margin_usd = cny_per_mt_to_usd_per_mt(margin_cny, inputs.usdcny)

    lme_price_cny = usd_per_mt_to_cny_per_mt(inputs.lme_price_usd_mt, inputs.usdcny)
    cif_premium_cny = usd_per_mt_to_cny_per_mt(leg.cif_premium_usd_mt, inputs.usdcny)
    vat_cny = leg.vat_rate * cif_value_cny

    waterfall = {
        "spread_cny": inputs.shfe_price_cny_mt - lme_price_cny,
        "cif_premium": -cif_premium_cny,
        "vat": -vat_cny,
        "admin_charge": -leg.admin_charge_cny_mt,
        "net_margin": margin_cny,
    }

    return ShfeArbResult(
        lme_price_usd_mt=inputs.lme_price_usd_mt,
        shfe_price_cny_mt=inputs.shfe_price_cny_mt,
        usdcny=inputs.usdcny,
        import_cost_cny_mt=import_cost_cny,
        arb_margin_cny_mt=margin_cny,
        arb_margin_usd_mt=margin_usd,
        # The SHFE price at which the import margin is exactly zero.
        breakeven_shfe_price_cny_mt=import_cost_cny,
        is_open=margin_cny > open_threshold_cny_mt,
        waterfall=waterfall,
    )
