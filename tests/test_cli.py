"""CLI smoke tests: end-to-end runs against the real config file."""

from __future__ import annotations

from pathlib import Path

import pytest

from metalarb.cli import load_assumptions, main

CONFIG = str(Path(__file__).parent.parent / "config" / "assumptions.yaml")


def test_load_assumptions_from_repo_config():
    assumptions = load_assumptions(Path(CONFIG))
    assert assumptions.lme_shfe.vat_rate == 0.13
    assert [s.name for s in assumptions.scenarios] == [
        "no_tariff",
        "phased_2027",
        "phased_2028",
        "full_232",
    ]


def test_load_assumptions_missing_file():
    with pytest.raises(FileNotFoundError):
        load_assumptions(Path("does/not/exist.yaml"))


def test_comex_all_scenarios(capsys):
    exit_code = main(
        ["--config", CONFIG, "comex", "--lme", "9500", "--comex-cents-lb", "480"]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "phased_2027" in out
    assert "full_232" in out
    assert "Reverse arb" in out
    assert "trapped" in out  # exit margin is negative at these prices


def test_comex_single_scenario(capsys):
    exit_code = main(
        [
            "--config", CONFIG,
            "comex", "--lme", "9500", "--comex-cents-lb", "480",
            "--scenario", "no_tariff",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "no_tariff" in out
    assert "phased_2027" not in out
    assert "OPEN" in out


def test_comex_unknown_scenario(capsys):
    exit_code = main(
        [
            "--config", CONFIG,
            "comex", "--lme", "9500", "--comex-cents-lb", "480",
            "--scenario", "bogus",
        ]
    )
    assert exit_code == 1
    assert "unknown scenario" in capsys.readouterr().err


def test_shfe(capsys):
    exit_code = main(
        [
            "--config", CONFIG,
            "shfe", "--lme", "9500", "--shfe-cny", "78000", "--usdcny", "7.10",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "879.20" in out
    assert "OPEN (buy LME, sell SHFE)" in out


def test_invalid_price_reports_error(capsys):
    exit_code = main(
        ["--config", CONFIG, "comex", "--lme", "-1", "--comex-cents-lb", "480"]
    )
    assert exit_code == 1
    assert "error:" in capsys.readouterr().err


def _stub_ingest_sources(monkeypatch):
    """Replace all network fetchers with fixed records."""
    from metalarb.models import PriceRecord

    monkeypatch.setattr(
        "metalarb.ingest.fetchers.fetch_comex_history",
        lambda start, end: [PriceRecord("2026-07-09", "yfinance", "HG=F", 4.85, "USD/lb", "USD")],
    )
    monkeypatch.setattr(
        "metalarb.ingest.fetchers.fetch_usdcny_history",
        lambda start, end: [PriceRecord("2026-07-09", "yfinance", "CNY=X", 7.10, "CNY/USD", "CNY")],
    )
    monkeypatch.setattr(
        "metalarb.ingest.fetchers.fetch_lme_settlements",
        lambda: [PriceRecord("2026-07-09", "westmetall", "LME_Cu_3M", 9610.0, "USD/mt", "USD")],
    )


def test_ingest_then_history(tmp_path, monkeypatch, capsys):
    _stub_ingest_sources(monkeypatch)
    db = str(tmp_path / "prices.sqlite")

    assert main(["ingest", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "COMEX HG=F (yfinance): upserted 1 rows" in out
    assert "LME settlements (Westmetall): upserted 1 rows" in out

    assert main(["history", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "HG=F" in out
    assert "LME_Cu_3M" in out
    assert "2026-07-09" in out


def test_ingest_partial_failure_still_succeeds(tmp_path, monkeypatch, capsys):
    """One dead source must not sink the whole ingest run."""
    _stub_ingest_sources(monkeypatch)

    def broken():
        raise ValueError("site unreachable")

    monkeypatch.setattr("metalarb.ingest.fetchers.fetch_lme_settlements", broken)
    db = str(tmp_path / "prices.sqlite")

    assert main(["ingest", "--db", db]) == 0
    captured = capsys.readouterr()
    assert "FAILED (site unreachable)" in captured.err
    assert "upserted 1 rows" in captured.out


def test_ingest_all_sources_fail(tmp_path, monkeypatch, capsys):
    def broken(*args):
        raise ValueError("down")

    for target in ("fetch_comex_history", "fetch_usdcny_history", "fetch_lme_settlements"):
        monkeypatch.setattr(f"metalarb.ingest.fetchers.{target}", broken)

    assert main(["ingest", "--db", str(tmp_path / "p.sqlite")]) == 1


def test_history_missing_db(tmp_path, capsys):
    exit_code = main(["history", "--db", str(tmp_path / "absent.sqlite")])
    assert exit_code == 1
    assert "run 'metalarb ingest' first" in capsys.readouterr().err


def test_history_unknown_symbol(tmp_path, monkeypatch, capsys):
    _stub_ingest_sources(monkeypatch)
    db = str(tmp_path / "prices.sqlite")
    main(["ingest", "--db", db])
    capsys.readouterr()

    assert main(["history", "--db", db, "--symbol", "XX=Y"]) == 1
    assert "no rows stored" in capsys.readouterr().err
