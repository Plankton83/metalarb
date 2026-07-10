"""Fetcher tests: all offline, using injected downloaders and fixture HTML."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from metalarb.ingest import fetchers

# Mixed European ('9.641,50') and English ('9,586.00') number formats plus a
# month-separator row, mirroring the quirks of the real Westmetall table.
WESTMETALL_HTML = """
<html><body>
<table>
  <tr><th>date</th><th>LME Copper cash-settlement</th>
      <th>LME Copper 3-month</th><th>stock</th></tr>
  <tr><td>July 2026</td><td></td><td></td><td></td></tr>
  <tr><td>08. July 2026</td><td>9.641,50</td><td>9.610,00</td><td>102.350</td></tr>
  <tr><td>07. July 2026</td><td>9,586.00</td><td>9,560.50</td><td>102,500</td></tr>
</table>
</body></html>
"""


def _stub_downloader(closes: dict[str, float]):
    def downloader(symbol: str, start: str, end: str | None) -> pd.Series:
        return pd.Series(closes.values(), index=pd.to_datetime(list(closes.keys())))

    return downloader


def test_fetch_comex_history_records():
    records = fetchers.fetch_comex_history(
        downloader=_stub_downloader({"2026-07-08": 4.80, "2026-07-09": 4.85})
    )
    assert len(records) == 2
    first = records[0]
    assert first.date == "2026-07-08"
    assert first.symbol == "HG=F"
    assert first.source == "yfinance"
    assert first.unit == "USD/lb"
    assert first.price == pytest.approx(4.80)


def test_fetch_usdcny_history_records():
    records = fetchers.fetch_usdcny_history(downloader=_stub_downloader({"2026-07-09": 7.10}))
    assert records[0].symbol == "CNY=X"
    assert records[0].unit == "CNY/USD"
    assert records[0].currency == "CNY"


def test_empty_downloader_result_raises():
    with pytest.raises(ValueError, match="no usable rows"):
        fetchers.fetch_comex_history(downloader=_stub_downloader({}))


def test_parse_westmetall_both_number_formats():
    """European '9.641,50' and English '9,586.00' must both parse correctly —
    naive thousands-separator handling would corrupt one of them (e.g. read
    9.641,50 as 9.6415)."""
    records = fetchers.parse_westmetall_html(WESTMETALL_HTML)
    by_key = {(r.date, r.symbol): r.price for r in records}
    assert by_key[("2026-07-08", "LME_Cu_cash")] == pytest.approx(9_641.50)
    assert by_key[("2026-07-08", "LME_Cu_3M")] == pytest.approx(9_610.00)
    assert by_key[("2026-07-07", "LME_Cu_cash")] == pytest.approx(9_586.00)
    assert by_key[("2026-07-07", "LME_Cu_3M")] == pytest.approx(9_560.50)
    assert len(records) == 4  # separator row skipped, stock column ignored


def test_parse_westmetall_units_and_source():
    record = fetchers.parse_westmetall_html(WESTMETALL_HTML)[0]
    assert record.source == "westmetall"
    assert record.unit == "USD/mt"
    assert record.currency == "USD"


def test_parse_westmetall_no_table():
    assert fetchers.parse_westmetall_html("<html><body><p>nope</p></body></html>") == []


def test_fetch_lme_settlements_writes_and_uses_cache(tmp_path):
    """First call fetches and caches; same-day second call parses the cache."""
    calls = {"count": 0}

    def fetching_stub() -> str:
        calls["count"] += 1
        return WESTMETALL_HTML

    today = date(2026, 7, 10)
    first = fetchers.fetch_lme_settlements(cache_dir=tmp_path, fetcher=fetching_stub, today=today)
    second = fetchers.fetch_lme_settlements(cache_dir=tmp_path, fetcher=fetching_stub, today=today)

    assert calls["count"] == 1
    assert (tmp_path / "westmetall_2026-07-10.html").exists()
    assert first == second
    assert len(first) == 4


def test_fetch_lme_settlements_unparseable_page_raises(tmp_path):
    with pytest.raises(ValueError, match="no LME settlement rows"):
        fetchers.fetch_lme_settlements(
            cache_dir=tmp_path, fetcher=lambda: "<html></html>", today=date(2026, 7, 10)
        )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("9.641,50", 9_641.50),
        ("9,586.00", 9_586.00),
        ("9586", 9_586.0),
        ("102.350", 102_350.0),   # European thousands, no decimals
        ("102,500", 102_500.0),   # English thousands, no decimals
        ("1.234.567,89", 1_234_567.89),
        ("", None),
        ("n/a", None),
    ],
)
def test_parse_table_number(raw: str, expected: float | None):
    result = fetchers._parse_table_number(raw)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("08. July 2026", "2026-07-08"),
        ("08. Jul 2026", "2026-07-08"),
        ("08.07.2026", "2026-07-08"),
        ("2026-07-08", "2026-07-08"),
        ("July 2026", None),
        ("average", None),
    ],
)
def test_parse_table_date(raw: str, expected: str | None):
    assert fetchers._parse_table_date(raw) == expected
