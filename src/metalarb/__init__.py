"""MetalArb: landed-cost physical copper arbitrage calculator (LME/COMEX/SHFE)."""

from metalarb.arb_lme_comex import compute_comex_arb, compute_exit_economics
from metalarb.arb_lme_shfe import compute_shfe_arb
from metalarb.models import (
    Assumptions,
    ComexArbInputs,
    ComexArbResult,
    ComexExitResult,
    Scenario,
    ShfeArbInputs,
    ShfeArbResult,
)
from metalarb.scenarios import results_table, run_scenarios

__version__ = "0.1.0"

__all__ = [
    "Assumptions",
    "ComexArbInputs",
    "ComexArbResult",
    "ComexExitResult",
    "Scenario",
    "ShfeArbInputs",
    "ShfeArbResult",
    "compute_comex_arb",
    "compute_exit_economics",
    "compute_shfe_arb",
    "results_table",
    "run_scenarios",
]
