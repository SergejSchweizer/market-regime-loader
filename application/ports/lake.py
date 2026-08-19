"""Application-facing contracts for tabular lake persistence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

import polars as pl


@dataclass(frozen=True, slots=True)
class ObservationBounds:
    """Observed date bounds in authoritative persisted data."""

    minimum: date | None
    maximum: date | None


@dataclass(frozen=True, slots=True)
class FrameDiff:
    """Pure logical classification of an incoming frame against retained data."""

    inserts: pl.DataFrame
    unchanged: pl.DataFrame
    revisions: pl.DataFrame

    @property
    def changed(self) -> pl.DataFrame:
        """Return inserted and revised rows in deterministic input order."""
        if self.inserts.is_empty():
            return self.revisions
        if self.revisions.is_empty():
            return self.inserts
        return pl.concat([self.inserts, self.revisions], how="vertical_relaxed")

    @property
    def has_changes(self) -> bool:
        """Return whether persistence work is required."""
        return not self.inserts.is_empty() or not self.revisions.is_empty()


class MonthlyFrameRepository(Protocol):
    """Narrow repository port used by later medallion services."""

    def read(self, paths: Sequence[Path], *, sort_by: Sequence[str]) -> pl.DataFrame:
        """Read exact authoritative monthly files in stable key order."""
        ...

    def observation_bounds(
        self, paths: Sequence[Path], *, date_column: str = "observation_date"
    ) -> ObservationBounds:
        """Return authoritative observed date bounds without synthetic calendar logic."""
        ...
