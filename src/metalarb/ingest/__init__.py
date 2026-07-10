"""Data ingestion (Phase 2): fetchers and SQLite price history store.

This package deliberately holds all of MetalArb's I/O for market data. The
calculation modules stay pure; ingested rows are raw source-native prices
(the future bronze layer in the Phase 4 medallion architecture).

Submodules are imported explicitly (``from metalarb.ingest import store``)
so that using the store never pulls in the heavier fetcher dependencies.
"""
