"""Pure authoritative Gold catalog records and consumer resolution Strategies."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class GoldBuildStatus(StrEnum):
    BUILDING = "building"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class GoldCatalogRecord:
    """Exact logical row of authoritative Gold manifest.parquet."""

    dataset_id: str
    build_id: str
    status: GoldBuildStatus
    current: bool
    started_at_utc: datetime
    completed_at_utc: datetime | None
    schema_version: int
    feature_version: int
    min_timestamp: datetime | None
    max_timestamp: datetime | None
    row_count: int | None
    data_path: str | None
    build_manifest_path: str | None
    plot_path: str | None
    pruned_at_utc: datetime | None

    @property
    def artifact_paths_complete(self) -> bool:
        return all(
            isinstance(value, str) and bool(value)
            for value in (self.data_path, self.build_manifest_path, self.plot_path)
        )

    @property
    def selectable_complete(self) -> bool:
        return (
            self.status is GoldBuildStatus.COMPLETE
            and self.completed_at_utc is not None
            and self.pruned_at_utc is None
            and self.artifact_paths_complete
        )


@dataclass(frozen=True, slots=True)
class GoldCompatibility:
    schema_version: int
    feature_version: int

    def matches(self, record: GoldCatalogRecord) -> bool:
        return (
            record.schema_version == self.schema_version
            and record.feature_version == self.feature_version
        )


class GoldResolutionStrategy(Protocol):
    """Pure Strategy selecting a catalog row without consulting filesystem state."""

    def resolve(
        self,
        records: Sequence[GoldCatalogRecord],
        compatibility: GoldCompatibility,
    ) -> GoldCatalogRecord: ...


def _single_current(records: Sequence[GoldCatalogRecord]) -> GoldCatalogRecord | None:
    current = [record for record in records if record.current]
    if len(current) > 1:
        raise ValueError("Gold catalog contains multiple current rows")
    return current[0] if current else None


def _completed_key(record: GoldCatalogRecord) -> tuple[datetime, str]:
    completed = record.completed_at_utc
    if completed is None:
        raise ValueError("selectable Gold build must have completed_at_utc")
    return completed, record.build_id


@dataclass(frozen=True, slots=True)
class StrictCurrentResolution:
    """Default fail-closed policy requiring one compatible selectable current row."""

    def resolve(
        self,
        records: Sequence[GoldCatalogRecord],
        compatibility: GoldCompatibility,
    ) -> GoldCatalogRecord:
        current = _single_current(records)
        if current is None:
            raise LookupError("Gold catalog has no current row")
        if not current.selectable_complete:
            raise LookupError("Gold current row is not a selectable complete build")
        if not compatibility.matches(current):
            raise LookupError("Gold current row is not compatible")
        return current


@dataclass(frozen=True, slots=True)
class LatestCompatibleResolution:
    """Explicit resilience policy falling back to newest compatible complete build."""

    def resolve(
        self,
        records: Sequence[GoldCatalogRecord],
        compatibility: GoldCompatibility,
    ) -> GoldCatalogRecord:
        current = _single_current(records)
        if current is not None and current.selectable_complete and compatibility.matches(current):
            return current
        candidates = [
            record
            for record in records
            if record.selectable_complete and compatibility.matches(record)
        ]
        if not candidates:
            raise LookupError("Gold catalog has no compatible complete build")
        return max(candidates, key=_completed_key)


STRICT_CURRENT = StrictCurrentResolution()
LATEST_COMPATIBLE = LatestCompatibleResolution()
