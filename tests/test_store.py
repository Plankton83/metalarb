"""SQLite price store tests (all against a temp database, no fixtures on disk)."""

from __future__ import annotations

import pytest

from metalarb.ingest import store
from metalarb.models import PriceRecord


@pytest.fixture
def records() -> list[PriceRecord]:
    return [
        PriceRecord("2026-07-08", "yfinance", "HG=F", 4.80, "USD/lb", "USD"),
        PriceRecord("2026-07-09", "yfinance", "HG=F", 4.85, "USD/lb", "USD"),
        PriceRecord("2026-07-09", "yfinance", "CNY=X", 7.10, "CNY/USD", "CNY"),
        PriceRecord("2026-07-09", "westmetall", "LME_Cu_3M", 9_610.0, "USD/mt", "USD"),
    ]


@pytest.fixture
def conn(tmp_path, records):
    connection = store.connect(tmp_path / "prices.sqlite")
    store.upsert_prices(connection, records)
    yield connection
    connection.close()


def test_connect_creates_parent_dirs(tmp_path):
    connection = store.connect(tmp_path / "nested" / "dir" / "prices.sqlite")
    assert (tmp_path / "nested" / "dir" / "prices.sqlite").exists()
    connection.close()


def test_upsert_returns_row_count(tmp_path, records):
    connection = store.connect(tmp_path / "prices.sqlite")
    assert store.upsert_prices(connection, records) == 4
    connection.close()


def test_upsert_is_idempotent(conn, records):
    """Re-ingesting the same rows converges to one row per natural key."""
    store.upsert_prices(conn, records)
    store.upsert_prices(conn, records)
    assert len(store.price_history(conn)) == 4


def test_upsert_replaces_on_natural_key(conn):
    """A corrected price for an existing (date, source, symbol) wins."""
    store.upsert_prices(
        conn, [PriceRecord("2026-07-09", "yfinance", "HG=F", 4.99, "USD/lb", "USD")]
    )
    assert store.latest_price(conn, "HG=F").price == pytest.approx(4.99)
    assert len(store.price_history(conn, "HG=F")) == 2


def test_latest_price_picks_most_recent_date(conn):
    latest = store.latest_price(conn, "HG=F")
    assert latest.date == "2026-07-09"
    assert latest.price == pytest.approx(4.85)


def test_latest_price_unknown_symbol(conn):
    assert store.latest_price(conn, "XX=Y") is None


def test_price_history_filter_and_order(conn):
    full = store.price_history(conn)
    assert list(full.columns) == [
        "date", "source", "symbol", "price", "unit", "currency", "ingested_at",
    ]
    assert list(full["date"]) == sorted(full["date"])
    only_hg = store.price_history(conn, "HG=F")
    assert set(only_hg["symbol"]) == {"HG=F"}
    assert len(only_hg) == 2


def test_symbols(conn):
    assert store.symbols(conn) == ["CNY=X", "HG=F", "LME_Cu_3M"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"date": "09/07/2026"},          # not ISO 8601
        {"price": 0.0},                  # zero price
        {"price": -4.8},                 # negative price
        {"symbol": ""},                  # empty key field
    ],
)
def test_price_record_validation(kwargs):
    base = {
        "date": "2026-07-09",
        "source": "yfinance",
        "symbol": "HG=F",
        "price": 4.8,
        "unit": "USD/lb",
        "currency": "USD",
    }
    with pytest.raises(ValueError):
        PriceRecord(**{**base, **kwargs})
