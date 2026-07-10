"""Time-series transforms: raw price rows -> conformed USD/mt -> daily arb metrics.

These are the silver (conform) and gold (metrics) transforms of the future
medallion architecture, written today as pure pandas functions: DataFrame in,
DataFrame out, no I/O, no global state.

Alignment note (documented simplification): COMEX closes in New York and LME
settles in London hours earlier, and Yahoo/Westmetall publish on their own
calendars. Rows are joined naively on calendar date, so each daily spread mixes
two observation times. Good enough for indicative analysis; a desk would align
timestamps properly.
"""

from __future__ import annotations

import pandas as pd

from metalarb.arb_lme_comex import compute_comex_arb
from metalarb.conversions import usd_per_lb_to_usd_per_mt
from metalarb.models import Assumptions, ComexArbInputs

COMEX_SYMBOL = "HG=F"
USDCNY_SYMBOL = "CNY=X"
LME_3M_SYMBOL = "LME_Cu_3M"
LME_CASH_SYMBOL = "LME_Cu_cash"


def conform_prices(raw: pd.DataFrame) -> pd.DataFrame:
    """Pivot raw price rows into one conformed USD/mt row per date (silver).

    Input columns: date, symbol, price, unit (as stored by the ingest layer).
    Output columns: date (index, ascending), lme_3m_usd_mt, lme_cash_usd_mt,
    comex_usd_mt, usdcny, spread_usd_mt — keeping only dates where both the
    LME 3M and COMEX legs exist, since the spread is undefined otherwise.
    COMEX arrives in Yahoo's USD/lb and is converted here, at the boundary.
    """
    required = {"date", "symbol", "price"}
    if raw.empty or not required.issubset(raw.columns):
        raise ValueError(f"raw price frame must have columns {sorted(required)} and rows")

    wide = raw.pivot_table(index="date", columns="symbol", values="price", aggfunc="last")

    frame = pd.DataFrame(index=wide.index)
    if LME_3M_SYMBOL in wide:
        frame["lme_3m_usd_mt"] = wide[LME_3M_SYMBOL]
    if LME_CASH_SYMBOL in wide:
        frame["lme_cash_usd_mt"] = wide[LME_CASH_SYMBOL]
    if COMEX_SYMBOL in wide:
        frame["comex_usd_mt"] = wide[COMEX_SYMBOL].map(
            lambda p: usd_per_lb_to_usd_per_mt(p) if pd.notna(p) else p
        )
    if USDCNY_SYMBOL in wide:
        frame["usdcny"] = wide[USDCNY_SYMBOL]

    for column in ("lme_3m_usd_mt", "comex_usd_mt"):
        if column not in frame:
            raise ValueError(f"cannot conform prices: no rows for {column}")

    frame = frame.dropna(subset=["lme_3m_usd_mt", "comex_usd_mt"]).sort_index()
    if frame.empty:
        raise ValueError("no dates have both an LME 3M and a COMEX observation")
    frame["spread_usd_mt"] = frame["comex_usd_mt"] - frame["lme_3m_usd_mt"]
    return frame


def arb_metrics_history(conformed: pd.DataFrame, assumptions: Assumptions) -> pd.DataFrame:
    """Daily arb metrics per tariff scenario (gold): one row per date x scenario.

    Reuses the Phase 1 pure calculator per observation, so the dashboard and
    the CLI can never disagree on a number.
    """
    if conformed.empty:
        raise ValueError("conformed price frame is empty")
    if not assumptions.scenarios:
        raise ValueError("no scenarios configured; define at least one in assumptions")

    rows = []
    for date, observation in conformed.iterrows():
        inputs = ComexArbInputs(
            lme_price_usd_mt=float(observation["lme_3m_usd_mt"]),
            comex_price_usd_mt=float(observation["comex_usd_mt"]),
        )
        for scenario in assumptions.scenarios:
            result = compute_comex_arb(inputs, assumptions, scenario)
            rows.append(
                {
                    "date": date,
                    "scenario": result.scenario_name,
                    "duty_rate": result.duty_rate,
                    "lme_3m_usd_mt": result.lme_price_usd_mt,
                    "comex_usd_mt": result.comex_price_usd_mt,
                    "spread_usd_mt": inputs.spread_usd_mt,
                    "landed_cost_usd_mt": result.landed_cost_usd_mt,
                    "breakeven_spread_usd_mt": result.breakeven_spread_usd_mt,
                    "gross_margin_usd_mt": result.gross_margin_usd_mt,
                    "is_open": result.is_open,
                    "exit_margin_usd_mt": result.exit.exit_margin_usd_mt,
                }
            )
    return pd.DataFrame(rows)
