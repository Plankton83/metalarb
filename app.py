"""MetalArb dashboard (Phase 3): COMEX-LME spread vs. tariff breakeven bands.

Run with:  streamlit run app.py

Presentation layer only — every number comes from the pure calculation modules
via metalarb.timeseries, so the dashboard and the CLI can never disagree.
Environment overrides: METALARB_DB (SQLite path), METALARB_CONFIG (assumptions
YAML path).
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from metalarb.cli import load_assumptions
from metalarb.ingest import store
from metalarb.models import Assumptions
from metalarb.timeseries import arb_metrics_history, conform_prices

DB_PATH = Path(os.environ.get("METALARB_DB", str(store.DEFAULT_DB_PATH)))
CONFIG_PATH = Path(os.environ.get("METALARB_CONFIG", str(Path("config") / "assumptions.yaml")))

# Reference dataviz palette (light mode). The spread is the story -> slot 1
# blue as the emphasis hue; scenario breakevens take the following categorical
# slots in fixed order, keyed by scenario name so filtering never repaints.
SPREAD_COLOR = "#2a78d6"
SCENARIO_SLOTS = ["#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"]
COST_COLOR = "#e34948"      # waterfall decreases (diverging warm pole)
GAIN_COLOR = "#2a78d6"      # waterfall increases (diverging cool pole)
TOTAL_COLOR = "#52514e"     # waterfall totals: secondary ink, not a series hue

SURFACE = "#fcfcfb"
GRID = "#e1e0d9"
MUTED = "#898781"
SECONDARY_INK = "#52514e"

_LAYOUT = {
    "plot_bgcolor": SURFACE,
    "paper_bgcolor": SURFACE,
    "font": {"family": 'system-ui, -apple-system, "Segoe UI", sans-serif', "color": SECONDARY_INK},
    "margin": {"l": 60, "r": 130, "t": 30, "b": 40},
    "xaxis": {"gridcolor": GRID, "linecolor": GRID, "tickfont": {"color": MUTED}},
    "yaxis": {"gridcolor": GRID, "linecolor": GRID, "tickfont": {"color": MUTED}},
    "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
}


@st.cache_data(ttl=300)
def load_metrics(db_path: str, config_path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Raw store -> conformed daily prices -> per-scenario metrics."""
    conn = store.connect(db_path)
    try:
        raw = store.price_history(conn)
    finally:
        conn.close()
    assumptions = load_assumptions(Path(config_path))
    conformed = conform_prices(raw)
    return conformed, arb_metrics_history(conformed, assumptions)


def scenario_colors(assumptions: Assumptions) -> dict[str, str]:
    return {
        scenario.name: SCENARIO_SLOTS[i % len(SCENARIO_SLOTS)]
        for i, scenario in enumerate(assumptions.scenarios)
    }


def spread_vs_breakeven_chart(
    metrics: pd.DataFrame, selected: list[str], colors: dict[str, str]
) -> go.Figure:
    """Actual COMEX-LME spread (emphasis) vs. per-scenario breakeven lines.

    Whenever the blue spread line sits above a scenario's breakeven line, the
    inbound arb is open under that tariff outcome.
    """
    figure = go.Figure()
    spread = metrics.drop_duplicates("date").sort_values("date")
    figure.add_trace(
        go.Scatter(
            x=spread["date"],
            y=spread["spread_usd_mt"],
            name="COMEX - LME spread",
            line={"color": SPREAD_COLOR, "width": 2.5},
            hovertemplate="%{y:,.0f} USD/mt<extra>spread</extra>",
        )
    )
    for name in selected:
        rows = metrics[metrics["scenario"] == name].sort_values("date")
        if rows.empty:
            continue
        figure.add_trace(
            go.Scatter(
                x=rows["date"],
                y=rows["breakeven_spread_usd_mt"],
                name=f"breakeven ({name})",
                line={"color": colors[name], "width": 2, "dash": "dash"},
                hovertemplate="%{y:,.0f} USD/mt<extra>" + name + "</extra>",
            )
        )
        # Direct label at the line end (relief rule for low-contrast hues).
        figure.add_annotation(
            x=rows["date"].iloc[-1],
            y=rows["breakeven_spread_usd_mt"].iloc[-1],
            text=name,
            showarrow=False,
            xanchor="left",
            xshift=6,
            font={"color": SECONDARY_INK, "size": 11},
        )
    figure.add_annotation(
        x=spread["date"].iloc[-1],
        y=spread["spread_usd_mt"].iloc[-1],
        text="spread",
        showarrow=False,
        xanchor="left",
        xshift=6,
        yshift=-12,  # keep clear of the lowest breakeven label when lines converge
        font={"color": SECONDARY_INK, "size": 11},
    )
    figure.update_layout(
        hovermode="x unified", yaxis_title="USD/mt", height=430, **_LAYOUT
    )
    return figure


def waterfall_chart(day: pd.Series) -> go.Figure:
    """Cost decomposition from raw spread to net margin for one date/scenario.

    Components are recomputed through the Phase 1 pure calculator rather than
    carried in the metrics frame, so the chart can never drift from the engine.
    """
    from metalarb.arb_lme_comex import compute_comex_arb
    from metalarb.models import ComexArbInputs, Scenario

    assumptions = load_assumptions(CONFIG_PATH)
    result = compute_comex_arb(
        ComexArbInputs(
            lme_price_usd_mt=float(day["lme_3m_usd_mt"]),
            comex_price_usd_mt=float(day["comex_usd_mt"]),
        ),
        assumptions,
        Scenario(str(day["scenario"]), float(day["duty_rate"])),
    )
    steps = [(k.replace("_", " "), v) for k, v in result.waterfall.items() if k != "net_margin"]
    labels = [label for label, _ in steps] + ["net margin"]
    values = [value for _, value in steps] + [result.gross_margin_usd_mt]

    figure = go.Figure(
        go.Waterfall(
            x=labels,
            y=values[:-1] + [0],
            measure=["relative"] * len(steps) + ["total"],
            increasing={"marker": {"color": GAIN_COLOR}},
            decreasing={"marker": {"color": COST_COLOR}},
            totals={"marker": {"color": TOTAL_COLOR}},
            connector={"line": {"color": GRID, "width": 1}},
            text=[f"{v + 0.0:,.0f}" for v in values],  # + 0.0 normalizes IEEE negative zero
            textposition="outside",
            textfont={"color": SECONDARY_INK},
            hovertemplate="%{x}: %{text} USD/mt<extra></extra>",
        )
    )
    figure.update_layout(yaxis_title="USD/mt", height=430, showlegend=False, **_LAYOUT)
    return figure


def main() -> None:
    st.set_page_config(page_title="MetalArb", page_icon=None, layout="wide")
    st.title("MetalArb — COMEX-LME copper tariff arb")
    st.caption(
        "Landed-cost analysis on delayed/indicative data and configurable assumptions. "
        "Analytical and educational tool — not trading signals."
    )

    try:
        conformed, metrics = load_metrics(str(DB_PATH), str(CONFIG_PATH))
    except (FileNotFoundError, ValueError) as exc:
        st.error(f"No usable price history: {exc}")
        st.info("Run `metalarb ingest` first, then reload this page.")
        st.stop()
        return

    assumptions = load_assumptions(CONFIG_PATH)
    colors = scenario_colors(assumptions)
    scenario_names = [s.name for s in assumptions.scenarios]
    dates = sorted(metrics["date"].unique())

    # Filters: one row above the charts.
    filter_range, filter_scenarios = st.columns([1, 2])
    with filter_range:
        window = st.selectbox("Date range", ["All history", "Last 90 days", "Last 30 days"])
    with filter_scenarios:
        selected = st.multiselect("Tariff scenarios", scenario_names, default=scenario_names)

    if window != "All history":
        days = 90 if window == "Last 90 days" else 30
        cutoff = (pd.Timestamp(dates[-1]) - pd.Timedelta(days=days)).date().isoformat()
        metrics = metrics[metrics["date"] >= cutoff]

    # KPI row: latest observation.
    latest_date = metrics["date"].max()
    latest = metrics[metrics["date"] == latest_date]
    latest_spread = float(latest["spread_usd_mt"].iloc[0])
    open_under = [
        str(row["scenario"]) for _, row in latest.iterrows() if bool(row["is_open"])
    ]
    exit_margin = float(latest["exit_margin_usd_mt"].iloc[0])

    kpi_spread, kpi_open, kpi_exit, kpi_date = st.columns(4)
    kpi_spread.metric("COMEX - LME spread", f"{latest_spread:,.0f} USD/mt")
    kpi_open.metric("Arb open under", ", ".join(open_under) if open_under else "no scenario")
    kpi_exit.metric(
        "Exit margin (US -> LME)",
        f"{exit_margin:,.0f} USD/mt",
        help="Reverse-arb economics: LME price flat minus exit freight, insurance and "
        "financing; duty paid on entry is sunk. Negative = metal is trapped.",
    )
    kpi_date.metric("Latest observation", str(latest_date))

    st.subheader("Spread vs. tariff breakeven bands")
    st.caption(
        "The arb is open under a scenario while the solid spread line is above that "
        "scenario's dashed breakeven line."
    )
    st.plotly_chart(
        spread_vs_breakeven_chart(metrics, selected, colors), use_container_width=True
    )

    st.subheader("Cost waterfall")
    pick_date, pick_scenario = st.columns([1, 1])
    with pick_date:
        available = sorted(metrics["date"].unique())
        chosen_date = st.selectbox("Date", available, index=len(available) - 1)
    with pick_scenario:
        chosen_scenario = st.selectbox("Scenario", scenario_names, index=0)

    day = metrics[(metrics["date"] == chosen_date) & (metrics["scenario"] == chosen_scenario)]
    if day.empty:
        st.warning("No observation for that date/scenario combination.")
    else:
        st.plotly_chart(waterfall_chart(day.iloc[0]), use_container_width=True)

    with st.expander("Data table (all computed metrics for the selected range)"):
        st.dataframe(
            metrics[metrics["scenario"].isin(selected)].reset_index(drop=True),
            use_container_width=True,
        )

    st.caption(
        f"Sources: COMEX HG=F and USDCNY via Yahoo Finance (delayed), LME indicative "
        f"settlements via Westmetall. Assumptions: {CONFIG_PATH}. Database: {DB_PATH}."
    )


main()
