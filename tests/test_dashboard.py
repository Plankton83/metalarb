"""Dashboard smoke tests via Streamlit's AppTest (headless, no browser)."""

from __future__ import annotations

from pathlib import Path

import pytest

from metalarb.ingest import store
from metalarb.models import PriceRecord

APP = str(Path(__file__).parent.parent / "app.py")


@pytest.fixture
def seeded_db(tmp_path) -> str:
    db_path = str(tmp_path / "prices.sqlite")
    conn = store.connect(db_path)
    records = []
    for day, (lme, hg) in {
        "2026-07-07": (9_400.0, 4.75),
        "2026-07-08": (9_500.0, 4.80),
        "2026-07-09": (9_600.0, 4.90),
    }.items():
        records.append(PriceRecord(day, "westmetall", "LME_Cu_3M", lme, "USD/mt", "USD"))
        records.append(PriceRecord(day, "yfinance", "HG=F", hg, "USD/lb", "USD"))
        records.append(PriceRecord(day, "yfinance", "CNY=X", 7.10, "CNY/USD", "CNY"))
    store.upsert_prices(conn, records)
    conn.close()
    return db_path


def _run_app(monkeypatch, db_path: str):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("METALARB_DB", db_path)
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    return app


def test_dashboard_renders_without_errors(monkeypatch, seeded_db):
    app = _run_app(monkeypatch, seeded_db)
    assert not app.exception
    assert "MetalArb" in app.title[0].value
    # KPI row present with the latest spread.
    assert any("spread" in m.label.lower() for m in app.metric)


def test_dashboard_scenario_toggle(monkeypatch, seeded_db):
    app = _run_app(monkeypatch, seeded_db)
    scenarios = app.multiselect[0]
    assert set(scenarios.value) == {"no_tariff", "phased_2027", "phased_2028", "full_232"}
    scenarios.set_value(["no_tariff"]).run()
    assert not app.exception


def test_dashboard_missing_db_shows_guidance(monkeypatch, tmp_path):
    app = _run_app(monkeypatch, str(tmp_path / "empty.sqlite"))
    assert not app.exception
    assert any("metalarb ingest" in info.value for info in app.info)
