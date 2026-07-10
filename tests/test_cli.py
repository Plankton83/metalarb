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
