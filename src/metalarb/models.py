"""Input, assumption and result schemas for MetalArb.

Everything internal is USD per metric tonne (USD/mt) unless the field name
says otherwise (SHFE-leg fields carry CNY/mt explicitly). All dataclasses are
frozen: calculations are pure functions over immutable inputs, which is what
lets the same transform logic port to PySpark later.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def _require_positive(value: float, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be strictly positive, got {value}")


def _require_non_negative(value: float, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value}")


@dataclass(frozen=True)
class MarketAssumptions:
    """Money-market parameters used for the cost of carry.

    Financing a cargo in transit is a real cost: the buyer pays for the metal
    at loading but only monetizes it on arrival, so the position is funded at
    a short rate (SOFR) plus the bank's spread for the transit window.
    """

    sofr: float
    funding_spread: float

    def __post_init__(self) -> None:
        _require_non_negative(self.sofr, "sofr")
        _require_non_negative(self.funding_spread, "funding_spread")

    @property
    def funding_rate(self) -> float:
        """All-in annualized funding rate (decimal)."""
        return self.sofr + self.funding_spread


@dataclass(frozen=True)
class ComexAssumptions:
    """Physical logistics parameters for the LME -> COMEX leg (all indicative)."""

    physical_premium_usd_mt: float
    freight_usd_mt: float
    insurance_rate: float
    transit_days: int
    customs_days: int
    warehouse_in_charges_usd_mt: float
    exit_freight_usd_mt: float

    def __post_init__(self) -> None:
        _require_non_negative(self.physical_premium_usd_mt, "physical_premium_usd_mt")
        _require_non_negative(self.freight_usd_mt, "freight_usd_mt")
        _require_non_negative(self.insurance_rate, "insurance_rate")
        _require_non_negative(self.transit_days, "transit_days")
        _require_non_negative(self.customs_days, "customs_days")
        _require_non_negative(self.warehouse_in_charges_usd_mt, "warehouse_in_charges_usd_mt")
        _require_non_negative(self.exit_freight_usd_mt, "exit_freight_usd_mt")

    @property
    def total_days(self) -> int:
        """Days of funding exposure: sea transit plus customs clearance."""
        return self.transit_days + self.customs_days


@dataclass(frozen=True)
class ShfeAssumptions:
    """Import-parity parameters for the LME -> SHFE leg (all indicative)."""

    cif_premium_usd_mt: float
    vat_rate: float
    admin_charge_cny_mt: float

    def __post_init__(self) -> None:
        _require_non_negative(self.cif_premium_usd_mt, "cif_premium_usd_mt")
        _require_non_negative(self.vat_rate, "vat_rate")
        _require_non_negative(self.admin_charge_cny_mt, "admin_charge_cny_mt")


@dataclass(frozen=True)
class Scenario:
    """A tariff scenario: a named ad-valorem duty rate applied on US import.

    Scenarios are first-class data, not code branches — adding one in the
    YAML config requires no code change. The COMEX-LME spread prices the
    market's expectation over these scenarios, which is why the tool treats
    the spread as a tariff-expectation instrument rather than a pure arb.
    """

    name: str
    duty_rate: float

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("scenario name must be non-empty")
        _require_non_negative(self.duty_rate, "duty_rate")


@dataclass(frozen=True)
class Assumptions:
    """Full assumption set, normally loaded from config/assumptions.yaml."""

    market: MarketAssumptions
    lme_comex: ComexAssumptions
    lme_shfe: ShfeAssumptions
    scenarios: tuple[Scenario, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Assumptions:
        """Build the assumption set from a parsed-YAML mapping (pure, no I/O)."""
        return cls(
            market=MarketAssumptions(**raw["market"]),
            lme_comex=ComexAssumptions(**raw["lme_comex"]),
            lme_shfe=ShfeAssumptions(**raw["lme_shfe"]),
            scenarios=tuple(Scenario(**s) for s in raw.get("scenarios", [])),
        )

    def scenario(self, name: str) -> Scenario:
        """Look up a scenario by name, raising ValueError if unknown."""
        for scenario in self.scenarios:
            if scenario.name == name:
                return scenario
        known = ", ".join(s.name for s in self.scenarios) or "<none>"
        raise ValueError(f"unknown scenario {name!r}; known scenarios: {known}")


@dataclass(frozen=True)
class ComexArbInputs:
    """Market prices for the LME -> COMEX leg, already normalized to USD/mt."""

    lme_price_usd_mt: float
    comex_price_usd_mt: float

    def __post_init__(self) -> None:
        _require_positive(self.lme_price_usd_mt, "lme_price_usd_mt")
        _require_positive(self.comex_price_usd_mt, "comex_price_usd_mt")

    @property
    def spread_usd_mt(self) -> float:
        """COMEX minus LME — the headline dislocation the arb tries to capture."""
        return self.comex_price_usd_mt - self.lme_price_usd_mt


@dataclass(frozen=True)
class ShfeArbInputs:
    """Market prices for the LME -> SHFE leg. SHFE quotes stay in CNY/mt."""

    lme_price_usd_mt: float
    shfe_price_cny_mt: float
    usdcny: float

    def __post_init__(self) -> None:
        _require_positive(self.lme_price_usd_mt, "lme_price_usd_mt")
        _require_positive(self.shfe_price_cny_mt, "shfe_price_cny_mt")
        _require_positive(self.usdcny, "usdcny")


@dataclass(frozen=True)
class ComexExitResult:
    """Economics of exiting US inventory back to an LME warehouse.

    This is the 'one-way door': metal re-delivered against LME warrants earns
    the LME price flat (the physical premium is paid by ex-warehouse buyers,
    not on delivery in), the exit bears freight, insurance and financing again,
    and the duty paid on the way in is sunk — no refund. When the spread
    narrows, US inventory therefore cannot economically leave.
    """

    exit_cost_usd_mt: float
    exit_margin_usd_mt: float
    waterfall: dict[str, float]


@dataclass(frozen=True)
class ComexArbResult:
    """Full result of the LME -> COMEX landed-cost comparison for one scenario."""

    scenario_name: str
    duty_rate: float
    lme_price_usd_mt: float
    comex_price_usd_mt: float
    landed_cost_usd_mt: float
    gross_margin_usd_mt: float
    breakeven_spread_usd_mt: float
    is_open: bool
    waterfall: dict[str, float]
    exit: ComexExitResult


@dataclass(frozen=True)
class ShfeArbResult:
    """Full result of the LME -> SHFE import-parity comparison."""

    lme_price_usd_mt: float
    shfe_price_cny_mt: float
    usdcny: float
    import_cost_cny_mt: float
    arb_margin_cny_mt: float
    arb_margin_usd_mt: float
    breakeven_shfe_price_cny_mt: float
    is_open: bool
    waterfall: dict[str, float]
