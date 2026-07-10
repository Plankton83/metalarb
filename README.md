# MetalArb — Physical Copper Arbitrage Calculator

A landed-cost physical arbitrage calculator for refined copper across three exchanges:
**LME (London), COMEX/CME (US), SHFE (Shanghai)**. All financial math is implemented
explicitly in numpy/pandas as pure, deterministic functions — no black-box finance
libraries.

> **This is an analytical / educational tool built on indicative parameters. Its
> outputs are not trading signals.**

## What it does

- **Leg 1 — LME → COMEX (the tariff arb):** computes the full landed cost of buying
  copper at the LME price, taking physical delivery ex-warehouse outside the US,
  shipping it to a CME-deliverable US warehouse and selling at the COMEX price —
  under a set of configurable tariff scenarios. It also computes the **reverse-arb
  exit** (US warehouse → LME warrant) to show why US inventory is trapped.
- **Leg 2 — LME → SHFE (import parity):** computes the China import cost
  (CIF value, VAT gross-up, administrative charges) against the SHFE price.
- A **tariff scenario engine** where scenarios are data in YAML, not code branches.
- A CLI that prints inputs, a full cost waterfall, margins, breakevens and an
  open/closed verdict per scenario.
- **Automated data ingestion (Phase 2):** COMEX `HG=F` and USDCNY history via
  yfinance (backfilled from 2024-01-01 by default), LME indicative settlement
  prices scraped respectfully from Westmetall (identifying User-Agent, per-day
  local cache), all persisted to a SQLite price history.
- **Streamlit dashboard (Phase 3):** the daily COMEX−LME spread against each
  tariff scenario's breakeven band, scenario toggles, a cost-waterfall chart
  for any stored date, KPI tiles (spread, open scenarios, exit margin), and a
  data-table view of every computed metric.

## Market context

US Section 232 copper tariffs created a historic COMEX–LME dislocation in 2025–26
(spreads around $400/t with peaks near a 27% premium, and roughly 900kt of copper
accumulated in US warehouses). A phased universal duty on refined copper (15% from
January 2027, 30% from January 2028) has been under decision.

The key insight this tool demonstrates: **the COMEX–LME spread is a
tariff-expectation instrument, not a classic reversible arbitrage.** The physical
trade has one-way doors. Metal imported into the US pays duty that is never
refunded, and metal re-delivered onto LME warrant earns the LME price flat while
paying freight, insurance and financing all over again. Once the spread narrows,
the inventory cannot economically exit — which is exactly what the reverse-arb view
quantifies.

## How to run

Requires Python ≥ 3.11.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run from the repo root (or pass `--config path/to/assumptions.yaml`):

```bash
# Leg 1: all tariff scenarios (default)
metalarb comex --lme 9500 --comex-cents-lb 480

# Leg 1: one scenario
metalarb comex --lme 9500 --comex-cents-lb 480 --scenario phased_2027

# Leg 2: China import parity
metalarb shfe --lme 9500 --shfe-cny 78000 --usdcny 7.10
```

Data ingestion (Phase 2 — requires the `ingest` extra, included in `[dev]`):

```bash
pip install -e ".[ingest]"

# Backfill COMEX + FX from 2024-01-01 and scrape today's LME settlements
metalarb ingest

# Options: --start / --end (yfinance range), --db PATH,
#          --skip-lme / --skip-yfinance (partial runs)
metalarb ingest --start 2025-01-01 --db data/metalarb.sqlite

# Inspect what's stored
metalarb history
metalarb history --symbol HG=F --limit 20
```

Dashboard (Phase 3 — requires the `dashboard` extra, included in `[dev]`):

```bash
pip install -e ".[dashboard]"
streamlit run app.py
```

The dashboard reads `data/metalarb.sqlite` (override with the `METALARB_DB`
env var; `METALARB_CONFIG` overrides the assumptions path), so run
`metalarb ingest` first. Every number on it comes through the same pure
calculation modules as the CLI — the dashboard is a presentation layer only.
The spread-vs-breakeven chart reads as: **the arb is open under a scenario
while the solid spread line sits above that scenario's dashed breakeven line.**

Prices are stored in **source-native units** (`HG=F` in USD/lb as Yahoo quotes
it, `CNY=X` as a rate, LME in USD/mt) with schema
`prices(date, source, symbol, price, unit, currency, ingested_at)` keyed on
`(date, source, symbol)`, so re-running an ingest upserts rather than
duplicates. This raw table is the future bronze layer of the Phase 4 medallion
architecture; conversion to USD/mt happens downstream at the point of use.
Computed arb metrics are deliberately **not** stored — they are recomputed from
prices + current assumptions so a config change never leaves stale numbers.

Tests and lint:

```bash
pytest          # includes coverage report
ruff check .
```

## Methodology & formulas

**Conventions.** Everything internal is USD per metric tonne; conversion happens
only at the ingestion boundary. COMEX HG (US cents/lb): `usd_mt = cents / 100 ×
2204.62`. SHFE (CNY/mt) converts at USDCNY. LME is USD/mt natively (3-month
rolling forward as the reference price). Financing accrues ACT/360.

**Leg 1 landed cost (USD/mt):**

```
landed_cost = (lme_price + physical_premium)      metal acquisition
            + freight                             sea freight to US Gulf
            + insurance_rate × (lme + premium)    cargo insurance
            + (lme + premium) × (sofr + spread) × (transit + customs days) / 360
            + warehouse_in_charges                US warehouse handling
            + duty_rate × (lme + premium)         scenario-dependent duty
```

- `gross_margin = comex_price − landed_cost`
- `breakeven_spread = landed_cost − lme_price` (the COMEX−LME spread at which
  margin = 0)
- The waterfall decomposes `spread → −premium → −freight → −insurance →
  −financing → −warehouse → −duty → net margin` and reconciles exactly. (The
  physical premium appears as an explicit step because the margin is measured
  against the LME screen price while metal is acquired at LME + premium.)

**Leg 1 reverse arb (US → LME exit):** metal valued at the COMEX price, plus exit
freight, insurance and financing at the same rates over the same window; revenue is
the LME price **flat** (warrant delivery earns no physical premium); the duty paid
on entry is sunk. `exit_margin = lme_price − exit_cost`.

**Leg 2 import parity (CNY/mt):**

```
import_cost = (lme_price + cif_premium) × usdcny × (1 + vat_rate) + admin_charge_cny
arb_margin  = shfe_price − import_cost
```

Positive margin ⇒ import window open (buy LME, sell SHFE). Margin also reported in
USD/mt for comparability. VAT is applied on the full CIF value because SHFE prices
are VAT-inclusive, making the comparison like-for-like.

All parameters live in [config/assumptions.yaml](config/assumptions.yaml);
scenarios are added there with no code change.

## Limitations

- **Delayed / indicative prices.** Nothing here is a live or licensed feed.
  Yahoo Finance data is delayed and unofficial; Westmetall publishes LME
  settlement prices as an indication only. Manual price inputs remain the
  reference path for the calculators.
- **Indicative freight and premiums.** Real desks use assessed physical premiums
  (Argus/Fastmarkets) and actual freight quotes; the config values are plausible
  placeholders only.
- **Simplified duty base.** Customs value is taken as LME price + physical premium.
  Real customs valuation (transaction value, includable freight/insurance,
  incoterms) can differ materially.
- **No queue or warrant mechanics.** LME queue times, warrant premiums/discounts,
  brand and location optionality are ignored.
- **No hedging leg or margin financing.** The calculator prices the physical move
  only; a real trade carries futures hedges on both exchanges, with margin calls
  and basis risk over the transit window.
- **Static rates.** SOFR, FX and premiums are point-in-time inputs, not curves.
- **Naive date alignment.** Daily spreads join COMEX closes (New York) with LME
  settlements (London) on calendar date, mixing observation times hours apart.

## Roadmap

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Core cost engine + scenario math + CLI, manual/config inputs, full pytest suite | **Done** |
| 2 | Automated data ingestion (yfinance COMEX + FX; LME indicative), SQLite price history | **Done** |
| 3 | Streamlit dashboard: spread vs. breakeven bands, scenario toggles, waterfall chart | **Done** |
| 4 | Databricks Free Edition migration: bronze/silver/gold Delta tables, scheduled Workflows, Databricks SQL dashboard | Planned |

The calculation modules are pure functions with no I/O or global state by design —
they become the silver→gold transforms in the Phase 4 medallion architecture.
