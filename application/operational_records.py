"""Typed operational inventory and ingestion-run records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from application.contracts import Provider


class RunMode(StrEnum):
    """Persisted source-run operation identity."""

    BOOTSTRAP = "bootstrap"
    UPDATE = "update"
    RECONCILE = "reconcile"


class RunStatus(StrEnum):
    """Durable source-run outcome."""

    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class InventoryRecord:
    """Observed authoritative Bronze coverage for one canonical series."""

    series_id: str
    provider: Provider
    min_observation_date: date | None
    max_observation_date: date | None
    row_count: int
    duplicate_key_count: int
    file_count: int

    @property
    def planning_latest(self) -> date | None:
        """Return the only inventory boundary valid for normal delta planning."""
        return self.max_observation_date


@dataclass(frozen=True, slots=True)
class IngestionRunRecord:
    """Durable audit record for one source execution."""

    run_id: str
    provider: Provider
    series_id: str
    mode: RunMode
    requested_start: date | None
    requested_end: date | None
    fetched_rows: int
    accepted_rows: int
    inserted_rows: int
    revised_rows: int
    written_partitions: int
    status: RunStatus
    started_at_utc: datetime
    completed_at_utc: datetime
    error_category: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must be non-empty")
        counts = (
            self.fetched_rows,
            self.accepted_rows,
            self.inserted_rows,
            self.revised_rows,
            self.written_partitions,
        )
        if any(value < 0 for value in counts):
            raise ValueError("run counts must be >= 0")
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("completed_at_utc cannot precede started_at_utc")
        if self.status is RunStatus.FAILED and (
            self.inserted_rows or self.revised_rows or self.written_partitions
        ):
            raise ValueError("failed run cannot claim non-durable writes")
