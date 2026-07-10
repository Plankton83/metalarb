"""Market data fetchers: yfinance (COMEX, FX) and Westmetall (LME indicative).

Design notes:

- Network access is isolated in two tiny functions (`_yf_closes`,
  `_http_get_westmetall`) that callers can inject replacements for, so every
  transformation is testable offline with fixtures.
- The Westmetall page is scraped respectfully: an identifying User-Agent, a
  30s timeout, and a per-day local cache so repeated runs on the same day
  never re-hit the site.
- Records keep source-native units (bronze-layer rule): HG=F in USD/lb as
  Yahoo quotes it, USDCNY as a CNY-per-USD rate, LME in USD/mt.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date as _date
from datetime import datetime
from pathlib import Path

import pandas as pd

from metalarb.models import PriceRecord

COMEX_SYMBOL = "HG=F"
USDCNY_SYMBOL = "CNY=X"
LME_CASH_SYMBOL = "LME_Cu_cash"
LME_3M_SYMBOL = "LME_Cu_3M"

# Default backfill start: captures the pre- and post-Section-232 dislocation.
DEFAULT_START = "2024-01-01"

WESTMETALL_URL = "https://www.westmetall.com/en/markdaten.php?action=table&field=LME_Cu_cash"
USER_AGENT = "MetalArb/0.2 (educational portfolio project; not for redistribution)"
DEFAULT_CACHE_DIR = Path("data") / "cache"

# (symbol, start, end) -> Close series indexed by timestamp.
Downloader = Callable[[str, str, str | None], pd.Series]
# () -> raw HTML of the Westmetall table page.
HtmlFetcher = Callable[[], str]


def _yf_closes(symbol: str, start: str, end: str | None) -> pd.Series:  # pragma: no cover
    """Fetch daily closes from Yahoo Finance (network)."""
    import yfinance as yf

    frame = yf.download(symbol, start=start, end=end, progress=False, auto_adjust=False)
    if frame is None or frame.empty:
        raise ValueError(f"no data returned by yfinance for {symbol}")
    closes = frame["Close"]
    if isinstance(closes, pd.DataFrame):  # yfinance >= 0.2.31 returns MultiIndex columns
        closes = closes.iloc[:, 0]
    return closes.dropna()


def _http_get_westmetall() -> str:  # pragma: no cover
    """Fetch the Westmetall LME copper table page (network)."""
    import requests

    response = requests.get(WESTMETALL_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.text


def _records_from_closes(
    closes: pd.Series, *, source: str, symbol: str, unit: str, currency: str
) -> list[PriceRecord]:
    """Turn a dated close series into validated PriceRecords (pure)."""
    records = []
    for timestamp, price in closes.items():
        records.append(
            PriceRecord(
                date=pd.Timestamp(timestamp).date().isoformat(),
                source=source,
                symbol=symbol,
                price=float(price),
                unit=unit,
                currency=currency,
            )
        )
    if not records:
        raise ValueError(f"no usable rows for {symbol}")
    return records


def fetch_comex_history(
    start: str = DEFAULT_START,
    end: str | None = None,
    downloader: Downloader | None = None,
) -> list[PriceRecord]:
    """Daily COMEX HG copper closes. Yahoo quotes HG=F in USD/lb."""
    closes = (downloader or _yf_closes)(COMEX_SYMBOL, start, end)
    return _records_from_closes(
        closes, source="yfinance", symbol=COMEX_SYMBOL, unit="USD/lb", currency="USD"
    )


def fetch_usdcny_history(
    start: str = DEFAULT_START,
    end: str | None = None,
    downloader: Downloader | None = None,
) -> list[PriceRecord]:
    """Daily USDCNY closes (CNY per USD)."""
    closes = (downloader or _yf_closes)(USDCNY_SYMBOL, start, end)
    return _records_from_closes(
        closes, source="yfinance", symbol=USDCNY_SYMBOL, unit="CNY/USD", currency="CNY"
    )


def fetch_lme_settlements(
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    fetcher: HtmlFetcher | None = None,
    today: _date | None = None,
) -> list[PriceRecord]:
    """LME copper indicative settlement prices (cash and 3-month) via Westmetall.

    The raw page is cached locally per calendar day: within one day, repeated
    ingests parse the cached HTML instead of re-requesting the site.
    """
    cache_dir = Path(cache_dir)
    cache_file = cache_dir / f"westmetall_{(today or _date.today()).isoformat()}.html"
    if cache_file.exists():
        html = cache_file.read_text()
    else:
        html = (fetcher or _http_get_westmetall)()
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(html)

    records = parse_westmetall_html(html)
    if not records:
        raise ValueError("no LME settlement rows could be parsed from the Westmetall page")
    return records


# --- Westmetall HTML parsing (pure) -----------------------------------------

_DATE_FORMATS = ("%d. %B %Y", "%d. %b %Y", "%d.%m.%Y", "%Y-%m-%d")


def _parse_table_date(raw: str) -> str | None:
    """Parse a Westmetall date cell to ISO 8601, or None if it isn't a date."""
    text = re.sub(r"\s+", " ", str(raw)).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_table_number(raw: str) -> float | None:
    """Parse a price cell tolerating both '9,586.00' and German '9.586,00'.

    When both separators appear, the right-most one is the decimal mark. A
    lone separator (either kind) is a decimal mark only when followed by one
    or two trailing digits; three trailing digits (or repeats) mean thousands
    — '9.641' is 9,641 USD/mt, not 9.641 (copper never trades at $9/t).
    """
    text = re.sub(r"[^\d.,\-]", "", str(raw))
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        if text.count(",") == 1 and re.search(r",\d{1,2}$", text):
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "." in text and not (text.count(".") == 1 and re.search(r"\.\d{1,2}$", text)):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_westmetall_html(html: str) -> list[PriceRecord]:
    """Extract LME cash and 3-month settlement records from the table page.

    Cells are read as raw strings via lxml (not pandas.read_html) so number
    parsing stays under our control — Westmetall mixes European and English
    number formatting, which naive parsers silently corrupt.
    """
    from lxml import html as lxml_html

    tree = lxml_html.fromstring(html)
    records: list[PriceRecord] = []

    for table in tree.xpath("//table"):
        rows = table.xpath(".//tr")
        if not rows:
            continue
        headers = [cell.text_content().strip().lower() for cell in rows[0].xpath("./th|./td")]
        cash_col = next((i for i, h in enumerate(headers) if "cash" in h), None)
        m3_col = next((i for i, h in enumerate(headers) if "3" in h and "month" in h), None)
        if cash_col is None and m3_col is None:
            continue

        for row in rows[1:]:
            cells = [cell.text_content().strip() for cell in row.xpath("./td")]
            if not cells:
                continue
            iso_date = _parse_table_date(cells[0])
            if iso_date is None:
                continue  # month-separator or header repeat rows
            for column, symbol in ((cash_col, LME_CASH_SYMBOL), (m3_col, LME_3M_SYMBOL)):
                if column is None or column >= len(cells):
                    continue
                price = _parse_table_number(cells[column])
                if price is None or price <= 0:
                    continue
                records.append(
                    PriceRecord(
                        date=iso_date,
                        source="westmetall",
                        symbol=symbol,
                        price=price,
                        unit="USD/mt",
                        currency="USD",
                    )
                )
    return records
