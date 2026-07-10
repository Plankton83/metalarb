"""Unit and FX conversions at the ingestion boundary.

Convention: everything internal is USD per metric tonne. These functions are
the only place quotes in exchange-native units (COMEX US cents/lb, SHFE
CNY/mt) are translated, so downstream cost math never mixes units.
"""

from __future__ import annotations

# Pounds per metric tonne, per the COMEX contract conversion convention.
LBS_PER_METRIC_TONNE = 2204.62


def cents_per_lb_to_usd_per_mt(price_cents_lb: float) -> float:
    """Convert a COMEX HG quote (US cents per pound) to USD per metric tonne.

    COMEX high-grade copper trades in cents/lb on 25,000 lb contracts; the
    physical market thinks in USD/mt, so: cents -> dollars (/100), then
    scale by pounds per tonne.
    """
    if price_cents_lb <= 0:
        raise ValueError(f"price_cents_lb must be strictly positive, got {price_cents_lb}")
    return price_cents_lb / 100 * LBS_PER_METRIC_TONNE


def usd_per_lb_to_usd_per_mt(price_usd_lb: float) -> float:
    """Convert a USD-per-pound quote to USD per metric tonne.

    Yahoo Finance quotes COMEX HG in USD/lb (e.g. 4.80), whereas the exchange
    convention is cents/lb; ingested rows keep the source-native USD/lb unit,
    so this is the conversion used when reading them back.
    """
    if price_usd_lb <= 0:
        raise ValueError(f"price_usd_lb must be strictly positive, got {price_usd_lb}")
    return price_usd_lb * LBS_PER_METRIC_TONNE


def usd_per_mt_to_cents_per_lb(price_usd_mt: float) -> float:
    """Inverse of :func:`cents_per_lb_to_usd_per_mt` (used for reporting)."""
    if price_usd_mt <= 0:
        raise ValueError(f"price_usd_mt must be strictly positive, got {price_usd_mt}")
    return price_usd_mt / LBS_PER_METRIC_TONNE * 100


def cny_per_mt_to_usd_per_mt(price_cny_mt: float, usdcny: float) -> float:
    """Convert a CNY/mt amount to USD/mt at the given USDCNY rate.

    USDCNY is quoted as CNY per USD, so CNY amounts are divided by the rate.
    Accepts any real CNY amount (margins can be negative); the FX rate must
    be strictly positive.
    """
    if usdcny <= 0:
        raise ValueError(f"usdcny must be strictly positive, got {usdcny}")
    return price_cny_mt / usdcny


def usd_per_mt_to_cny_per_mt(price_usd_mt: float, usdcny: float) -> float:
    """Convert a USD/mt amount to CNY/mt at the given USDCNY rate."""
    if usdcny <= 0:
        raise ValueError(f"usdcny must be strictly positive, got {usdcny}")
    return price_usd_mt * usdcny
