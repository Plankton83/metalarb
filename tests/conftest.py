"""Shared fixtures: the indicative assumption set from config/assumptions.yaml.

Built in code (not loaded from disk) so the calculation tests stay free of
I/O and the expected values in docstrings are self-contained.
"""

from __future__ import annotations

import pytest

from metalarb.models import (
    Assumptions,
    ComexAssumptions,
    MarketAssumptions,
    Scenario,
    ShfeAssumptions,
)


@pytest.fixture
def assumptions() -> Assumptions:
    return Assumptions(
        market=MarketAssumptions(sofr=0.045, funding_spread=0.015),
        lme_comex=ComexAssumptions(
            physical_premium_usd_mt=250,
            freight_usd_mt=120,
            insurance_rate=0.003,
            transit_days=30,
            customs_days=5,
            warehouse_in_charges_usd_mt=25,
            exit_freight_usd_mt=120,
        ),
        lme_shfe=ShfeAssumptions(
            cif_premium_usd_mt=100,
            vat_rate=0.13,
            admin_charge_cny_mt=100,
        ),
        scenarios=(
            Scenario("no_tariff", 0.00),
            Scenario("phased_2027", 0.15),
            Scenario("phased_2028", 0.30),
            Scenario("full_232", 0.50),
        ),
    )
