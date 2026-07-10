"""SQLite price history store.

Schema (per the project spec): prices(date, source, symbol, price, unit,
currency, ingested_at) with (date, source, symbol) as the natural key, so
re-running an ingest upserts rather than duplicates. Rows keep source-native
units; this table is the bronze layer of the future medallion architecture.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from metalarb.models import PriceRecord

DEFAULT_DB_PATH = Path("data") / "metalarb.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    date        TEXT NOT NULL,
    source      TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    price       REAL NOT NULL,
    unit        TEXT NOT NULL,
    currency    TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    PRIMARY KEY (date, source, symbol)
)
"""


def connect(path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open (creating if needed) the price database and ensure the schema."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def upsert_prices(conn: sqlite3.Connection, records: Iterable[PriceRecord]) -> int:
    """Insert or replace price rows; returns the number of rows written.

    INSERT OR REPLACE on the natural key makes ingestion idempotent: fetching
    the same date range twice converges to one row per (date, source, symbol),
    with ingested_at recording the latest fetch time.
    """
    now = datetime.now(UTC).isoformat(timespec="seconds")
    rows = [(r.date, r.source, r.symbol, r.price, r.unit, r.currency, now) for r in records]
    conn.executemany(
        "INSERT OR REPLACE INTO prices VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def latest_price(conn: sqlite3.Connection, symbol: str) -> PriceRecord | None:
    """The most recent stored observation for a symbol, or None."""
    row = conn.execute(
        "SELECT date, source, symbol, price, unit, currency FROM prices "
        "WHERE symbol = ? ORDER BY date DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    return PriceRecord(*row) if row else None


def price_history(conn: sqlite3.Connection, symbol: str | None = None) -> pd.DataFrame:
    """All stored rows (optionally for one symbol), sorted by date then symbol."""
    query = "SELECT date, source, symbol, price, unit, currency, ingested_at FROM prices"
    params: tuple[str, ...] = ()
    if symbol is not None:
        query += " WHERE symbol = ?"
        params = (symbol,)
    query += " ORDER BY date, symbol"
    return pd.read_sql_query(query, conn, params=params)


def symbols(conn: sqlite3.Connection) -> list[str]:
    """Distinct symbols present in the store."""
    return [row[0] for row in conn.execute("SELECT DISTINCT symbol FROM prices ORDER BY symbol")]
