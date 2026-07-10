"""Silver/gold transform tests: conform_prices and arb_metrics_history."""

from __future__ import annotations

import pandas as pd
import pytest

from metalarb.timeseries import arb_metrics_history, conform_prices


def _raw_frame(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"date": d, "symbol": s, "price": p, "unit": "x", "currency": "x"} for d, s, p in rows]
    )


@pytest.fixture
def raw() -> pd.DataFrame:
    return _raw_frame(
        [
            ("2026-07-08", "LME_Cu_3M", 9_500.0),
            ("2026-07-08", "LME_Cu_cash", 9_450.0),
            ("2026-07-08", "HG=F", 4.80),
            ("2026-07-08", "CNY=X", 7.10),
            ("2026-07-09", "LME_Cu_3M", 9_600.0),
            ("2026-07-09", "HG=F", 4.90),
            # 07-10: COMEX only -> spread undefined -> row dropped
            ("2026-07-10", "HG=F", 4.95),
        ]
    )


def test_conform_known_values(raw):
    """4.80 USD/lb * 2204.62 = 10,582.176 USD/mt; spread = 1,082.176."""
    conformed = conform_prices(raw)
    day = conformed.loc["2026-07-08"]
    assert day["comex_usd_mt"] == pytest.approx(10_582.176)
    assert day["lme_3m_usd_mt"] == pytest.approx(9_500.0)
    assert day["lme_cash_usd_mt"] == pytest.approx(9_450.0)
    assert day["usdcny"] == pytest.approx(7.10)
    assert day["spread_usd_mt"] == pytest.approx(1_082.176)


def test_conform_drops_incomplete_dates(raw):
    """Dates missing either spread leg are excluded (2026-07-10 has COMEX only)."""
    conformed = conform_prices(raw)
    assert list(conformed.index) == ["2026-07-08", "2026-07-09"]


def test_conform_missing_leg_entirely():
    with pytest.raises(ValueError, match="lme_3m_usd_mt"):
        conform_prices(_raw_frame([("2026-07-08", "HG=F", 4.80)]))


def test_conform_empty_frame():
    with pytest.raises(ValueError):
        conform_prices(pd.DataFrame())


def test_conform_no_overlapping_dates():
    with pytest.raises(ValueError, match="both"):
        conform_prices(
            _raw_frame([("2026-07-08", "HG=F", 4.80), ("2026-07-09", "LME_Cu_3M", 9_500.0)])
        )


def test_metrics_history_matches_phase1_calculator(raw, assumptions):
    """The gold transform must reproduce the hand-computed Phase 1 values:
    at LME 9,500 / COMEX 10,582.176 under phased_2027, margin = -861.449."""
    metrics = arb_metrics_history(conform_prices(raw), assumptions)
    assert len(metrics) == 2 * 4  # 2 dates x 4 scenarios
    row = metrics[(metrics["date"] == "2026-07-08") & (metrics["scenario"] == "phased_2027")]
    assert row["gross_margin_usd_mt"].iloc[0] == pytest.approx(-861.449)
    assert row["breakeven_spread_usd_mt"].iloc[0] == pytest.approx(1_943.625)
    assert not bool(row["is_open"].iloc[0])
    no_tariff = metrics[(metrics["date"] == "2026-07-08") & (metrics["scenario"] == "no_tariff")]
    assert bool(no_tariff["is_open"].iloc[0])
    assert no_tariff["exit_margin_usd_mt"].iloc[0] == pytest.approx(-1_295.651888)


def test_metrics_history_empty_scenarios(raw, assumptions):
    from dataclasses import replace

    with pytest.raises(ValueError, match="no scenarios"):
        arb_metrics_history(conform_prices(raw), replace(assumptions, scenarios=()))


def test_metrics_history_empty_frame(assumptions):
    with pytest.raises(ValueError, match="empty"):
        arb_metrics_history(pd.DataFrame(), assumptions)
