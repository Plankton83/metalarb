"""Tariff scenario engine for the LME -> COMEX leg.

Scenarios are data (name + duty rate) loaded from config, so extending the
analysis to a new tariff outcome is a YAML edit, not a code change.
"""

from __future__ import annotations

import pandas as pd

from metalarb.arb_lme_comex import compute_comex_arb
from metalarb.models import Assumptions, ComexArbInputs, ComexArbResult


def run_scenarios(
    inputs: ComexArbInputs,
    assumptions: Assumptions,
    open_threshold_usd_mt: float = 0.0,
) -> list[ComexArbResult]:
    """Run the COMEX arb under every configured tariff scenario.

    Raises ValueError if the assumption set defines no scenarios — a silent
    empty result would look like 'no arb' rather than 'no analysis'.
    """
    if not assumptions.scenarios:
        raise ValueError("no scenarios configured; define at least one in assumptions")
    return [
        compute_comex_arb(inputs, assumptions, scenario, open_threshold_usd_mt)
        for scenario in assumptions.scenarios
    ]


def results_table(results: list[ComexArbResult]) -> pd.DataFrame:
    """Flatten scenario results into a comparison table (one row per scenario)."""
    if not results:
        raise ValueError("results list is empty")
    return pd.DataFrame(
        [
            {
                "scenario": r.scenario_name,
                "duty_rate": r.duty_rate,
                "landed_cost_usd_mt": r.landed_cost_usd_mt,
                "comex_price_usd_mt": r.comex_price_usd_mt,
                "gross_margin_usd_mt": r.gross_margin_usd_mt,
                "breakeven_spread_usd_mt": r.breakeven_spread_usd_mt,
                "is_open": r.is_open,
            }
            for r in results
        ]
    )
