"""Scenario engine tests: extensibility, ordering properties, error handling."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise

import pandas as pd
import pytest

from metalarb.models import Assumptions, ComexArbInputs, Scenario
from metalarb.scenarios import results_table, run_scenarios


@pytest.fixture
def inputs() -> ComexArbInputs:
    return ComexArbInputs(lme_price_usd_mt=9_500, comex_price_usd_mt=10_582.176)


def test_runs_all_configured_scenarios(inputs, assumptions):
    results = run_scenarios(inputs, assumptions)
    assert [r.scenario_name for r in results] == [
        "no_tariff",
        "phased_2027",
        "phased_2028",
        "full_232",
    ]


def test_margin_monotonic_across_scenarios(inputs, assumptions):
    """Scenarios are ordered by rising duty, so margins must strictly fall."""
    margins = [r.gross_margin_usd_mt for r in run_scenarios(inputs, assumptions)]
    assert all(a > b for a, b in pairwise(margins))


def test_extensible_without_code_change(inputs, assumptions):
    """Adding a scenario to the config (YAML in practice) needs no code change."""
    extended = replace(
        assumptions, scenarios=(*assumptions.scenarios, Scenario("custom_10pct", 0.10))
    )
    results = run_scenarios(inputs, extended)
    assert results[-1].scenario_name == "custom_10pct"
    assert results[-1].duty_rate == 0.10


def test_empty_scenarios_raise(inputs, assumptions):
    with pytest.raises(ValueError, match="no scenarios"):
        run_scenarios(inputs, replace(assumptions, scenarios=()))


def test_results_table_shape_and_content(inputs, assumptions):
    table = results_table(run_scenarios(inputs, assumptions))
    assert isinstance(table, pd.DataFrame)
    assert list(table.columns) == [
        "scenario",
        "duty_rate",
        "landed_cost_usd_mt",
        "comex_price_usd_mt",
        "gross_margin_usd_mt",
        "breakeven_spread_usd_mt",
        "is_open",
    ]
    assert len(table) == 4
    # Known values from the hand calculations in test_arb_lme_comex.
    row = table.set_index("scenario").loc["phased_2027"]
    assert row["landed_cost_usd_mt"] == pytest.approx(11_443.625)
    assert bool(row["is_open"]) is False


def test_results_table_empty_raises():
    with pytest.raises(ValueError):
        results_table([])


def test_scenario_lookup(assumptions):
    assert assumptions.scenario("phased_2028").duty_rate == 0.30
    with pytest.raises(ValueError, match="unknown scenario"):
        assumptions.scenario("does_not_exist")


def test_scenario_validation():
    with pytest.raises(ValueError):
        Scenario(name="", duty_rate=0.1)
    with pytest.raises(ValueError):
        Scenario(name="negative", duty_rate=-0.1)


def test_assumptions_from_dict_round_trip(assumptions):
    """Assumptions.from_dict builds the same objects the YAML loader would."""
    raw = {
        "market": {"sofr": 0.045, "funding_spread": 0.015},
        "lme_comex": {
            "physical_premium_usd_mt": 250,
            "freight_usd_mt": 120,
            "insurance_rate": 0.003,
            "transit_days": 30,
            "customs_days": 5,
            "warehouse_in_charges_usd_mt": 25,
            "exit_freight_usd_mt": 120,
        },
        "lme_shfe": {"cif_premium_usd_mt": 100, "vat_rate": 0.13, "admin_charge_cny_mt": 100},
        "scenarios": [
            {"name": "no_tariff", "duty_rate": 0.00},
            {"name": "phased_2027", "duty_rate": 0.15},
            {"name": "phased_2028", "duty_rate": 0.30},
            {"name": "full_232", "duty_rate": 0.50},
        ],
    }
    assert Assumptions.from_dict(raw) == assumptions
