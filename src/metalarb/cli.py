"""Command-line interface for MetalArb.

This is the only module with I/O: it loads the YAML assumptions, normalizes
quotes to internal units at the boundary, calls the pure calculation modules
and formats the results. Keeping I/O out of the calculation modules is what
makes them portable to PySpark later.

Usage:
    metalarb comex --lme 9500 --comex-cents-lb 480 [--scenario phased_2027 | --all-scenarios]
    metalarb shfe  --lme 9500 --shfe-cny 78000 --usdcny 7.10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from tabulate import tabulate

from metalarb.arb_lme_comex import compute_comex_arb
from metalarb.arb_lme_shfe import compute_shfe_arb
from metalarb.conversions import cents_per_lb_to_usd_per_mt
from metalarb.models import Assumptions, ComexArbInputs, ComexArbResult, ShfeArbInputs
from metalarb.scenarios import results_table, run_scenarios

DEFAULT_CONFIG = Path("config") / "assumptions.yaml"


def load_assumptions(path: Path) -> Assumptions:
    """Read and validate the assumptions YAML file."""
    if not path.exists():
        raise FileNotFoundError(
            f"assumptions file not found: {path} (pass --config or run from the repo root)"
        )
    with path.open() as fh:
        raw = yaml.safe_load(fh)
    return Assumptions.from_dict(raw)


def _fmt(value: float) -> str:
    return f"{value + 0.0:,.2f}"  # + 0.0 normalizes IEEE negative zero


def _print_waterfall(waterfall: dict[str, float], unit: str) -> None:
    rows = [(name, _fmt(value)) for name, value in waterfall.items()]
    print(
        tabulate(
            rows,
            headers=["component", unit],
            tablefmt="simple",
            stralign="right",
            disable_numparse=True,
        )
    )


def _print_comex(results: list[ComexArbResult], lme: float, comex_usd_mt: float) -> None:
    print("\nInputs (USD/mt)")
    print(
        tabulate(
            [
                ("LME 3M", _fmt(lme)),
                ("COMEX", _fmt(comex_usd_mt)),
                ("spread (COMEX - LME)", _fmt(comex_usd_mt - lme)),
            ],
            tablefmt="simple",
            stralign="right",
            disable_numparse=True,
        )
    )

    print("\nScenario comparison (USD/mt)")
    table = results_table(results)
    table["verdict"] = table["is_open"].map({True: "OPEN", False: "CLOSED"})
    print(
        table.drop(columns=["is_open"]).to_string(
            index=False, float_format=lambda v: f"{v:,.2f}"
        )
    )

    for result in results:
        print(f"\nCost waterfall - scenario '{result.scenario_name}' (USD/mt)")
        _print_waterfall(result.waterfall, "USD/mt")

    # Exit economics carry no duty, so they are identical across scenarios.
    exit_result = results[0].exit
    print("\nReverse arb: US warehouse -> LME warehouse (USD/mt)")
    print("(duty paid on import is sunk - not refunded on exit)")
    _print_waterfall(exit_result.waterfall, "USD/mt")
    verdict = "OPEN" if exit_result.exit_margin_usd_mt > 0 else "CLOSED (metal trapped)"
    print(f"exit margin: {_fmt(exit_result.exit_margin_usd_mt)} USD/mt -> {verdict}")


def _cmd_comex(args: argparse.Namespace) -> int:
    assumptions = load_assumptions(args.config)
    comex_usd_mt = cents_per_lb_to_usd_per_mt(args.comex_cents_lb)
    inputs = ComexArbInputs(lme_price_usd_mt=args.lme, comex_price_usd_mt=comex_usd_mt)

    if args.scenario:
        scenario = assumptions.scenario(args.scenario)
        results = [compute_comex_arb(inputs, assumptions, scenario)]
    else:
        # Default (and --all-scenarios): run every configured scenario.
        results = run_scenarios(inputs, assumptions)

    _print_comex(results, args.lme, comex_usd_mt)
    return 0


def _cmd_shfe(args: argparse.Namespace) -> int:
    assumptions = load_assumptions(args.config)
    inputs = ShfeArbInputs(
        lme_price_usd_mt=args.lme,
        shfe_price_cny_mt=args.shfe_cny,
        usdcny=args.usdcny,
    )
    result = compute_shfe_arb(inputs, assumptions)

    print("\nInputs")
    print(
        tabulate(
            [
                ("LME 3M (USD/mt)", _fmt(result.lme_price_usd_mt)),
                ("SHFE (CNY/mt)", _fmt(result.shfe_price_cny_mt)),
                ("USDCNY", f"{result.usdcny:.4f}"),
            ],
            tablefmt="simple",
            stralign="right",
            disable_numparse=True,
        )
    )

    print("\nImport parity waterfall (CNY/mt)")
    _print_waterfall(result.waterfall, "CNY/mt")

    verdict = "OPEN (buy LME, sell SHFE)" if result.is_open else "CLOSED"
    print(f"\nimport cost:      {_fmt(result.import_cost_cny_mt)} CNY/mt")
    print(f"breakeven SHFE:   {_fmt(result.breakeven_shfe_price_cny_mt)} CNY/mt")
    print(f"margin:           {_fmt(result.arb_margin_cny_mt)} CNY/mt")
    print(f"margin:           {_fmt(result.arb_margin_usd_mt)} USD/mt")
    print(f"verdict:          {verdict}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="metalarb",
        description="Landed-cost physical copper arbitrage calculator (analytical tool, "
        "not trading advice).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"path to assumptions YAML (default: {DEFAULT_CONFIG})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    comex = sub.add_parser("comex", help="LME -> COMEX tariff arb")
    comex.add_argument("--lme", type=float, required=True, help="LME 3M price, USD/mt")
    comex.add_argument(
        "--comex-cents-lb", type=float, required=True, help="COMEX HG price, US cents/lb"
    )
    group = comex.add_mutually_exclusive_group()
    group.add_argument("--scenario", help="run a single named tariff scenario")
    group.add_argument(
        "--all-scenarios",
        action="store_true",
        help="run every configured scenario (default behaviour)",
    )
    comex.set_defaults(func=_cmd_comex)

    shfe = sub.add_parser("shfe", help="LME -> SHFE import parity arb")
    shfe.add_argument("--lme", type=float, required=True, help="LME 3M price, USD/mt")
    shfe.add_argument("--shfe-cny", type=float, required=True, help="SHFE price, CNY/mt")
    shfe.add_argument("--usdcny", type=float, required=True, help="USDCNY exchange rate")
    shfe.set_defaults(func=_cmd_shfe)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
