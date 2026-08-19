"""Filesystem repository for canonical monthly Silver series."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from application.contracts import SeriesContract
from application.paths import LakePaths
from application.ports.lake import FrameDiff
from application.silver import SILVER_SCHEMA, canonicalize_silver
from ingestion.parquet_repository import read_monthly, upsert_monthly

_SILVER_KEY = ("series_id", "observation_date")


class SilverSeriesRepository:
    """Repository/Adapter that builds one selected Silver series from retained Bronze."""

    def __init__(self, paths: LakePaths) -> None:
        self._paths = paths

    def _bronze_paths(self, contract: SeriesContract) -> tuple[Path, ...]:
        root = (
            self._paths.root
            / "bronze"
            / f"provider={contract.provider.value}"
            / f"series={contract.series_id}"
        )
        return tuple(sorted(root.glob("year=*/month=*/data.parquet"))) if root.exists() else ()

    def _silver_paths(self, contract: SeriesContract) -> tuple[Path, ...]:
        root = self._paths.root / "silver" / f"series={contract.series_id}"
        return tuple(sorted(root.glob("year=*/month=*/data.parquet"))) if root.exists() else ()

    def read(self, contract: SeriesContract) -> pl.DataFrame:
        frame = read_monthly(self._silver_paths(contract), sort_by=())
        if not frame.columns:
            return pl.DataFrame(schema=SILVER_SCHEMA)
        if frame.schema != SILVER_SCHEMA:
            raise ValueError("invalid persisted Silver schema")
        return frame.sort(list(_SILVER_KEY))

    def build(self, contract: SeriesContract) -> FrameDiff:
        bronze = read_monthly(
            self._bronze_paths(contract),
            sort_by=("provider", "series_id", "observation_date"),
        )
        candidate = canonicalize_silver(contract, bronze)
        existing = self.read(contract)
        diff, _ = upsert_monthly(
            existing,
            candidate,
            key=_SILVER_KEY,
            date_column="observation_date",
            path_for_date=lambda day: self._paths.silver_month(contract.series_id, day),
        )
        return diff
