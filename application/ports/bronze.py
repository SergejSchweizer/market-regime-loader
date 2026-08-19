"""Application-facing Bronze transaction boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import polars as pl

from application.contracts import SeriesContract
from application.operational_records import IngestionRunRecord
from application.ports.lake import FrameDiff, ObservationBounds
from application.state import IngestionState


@dataclass(frozen=True, slots=True)
class PreparedBronze:
    """Pure staged Bronze mutation; construction performs no durable writes."""

    contract: SeriesContract
    merged: pl.DataFrame
    diff: FrameDiff
    post_bounds: ObservationBounds
    written_partitions: int


class BronzeUnitOfWork(Protocol):
    """Atomic application boundary for one series ingestion transaction."""

    def bounds(self, contract: SeriesContract) -> ObservationBounds:
        """Read authoritative Bronze observation bounds."""
        ...

    def state(self, contract: SeriesContract) -> IngestionState:
        """Read cached operational state without overriding Bronze truth."""
        ...

    def prepare(self, contract: SeriesContract, incoming: pl.DataFrame) -> PreparedBronze:
        """Stage a logical diff without mutating authoritative storage."""
        ...

    def commit_success(
        self,
        prepared: PreparedBronze,
        run: IngestionRunRecord,
        state: IngestionState,
    ) -> None:
        """Commit Bronze, success-run audit, and state as one compensated transaction."""
        ...

    def record_failure(self, run: IngestionRunRecord) -> None:
        """Persist a safe failed-run record without advancing Bronze or state."""
        ...
