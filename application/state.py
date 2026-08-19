"""Typed ingestion-state contract and durability transition rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime

from application.contracts import Provider
from application.planner import FetchInstruction, OperationMode
from application.ports.lake import ObservationBounds


@dataclass(frozen=True, slots=True)
class IngestionState:
    """Durable per-provider/series ingestion progress."""

    provider: Provider
    series_id: str
    last_success_utc: datetime | None = None
    last_observed_date: date | None = None
    last_requested_start: date | None = None
    last_requested_end: date | None = None
    mode: OperationMode | None = None
    fetched_row_count: int = 0
    accepted_row_count: int = 0
    changed_row_count: int = 0
    last_reconcile_utc: datetime | None = None

    def authoritative_latest(self, bounds: ObservationBounds) -> date | None:
        """Return Bronze truth; stale cache may never broaden source scope."""
        if self.last_observed_date is None:
            return bounds.maximum
        if bounds.maximum is None:
            raise ValueError("state claims observations but authoritative Bronze is empty")
        if self.last_observed_date != bounds.maximum:
            return bounds.maximum
        return self.last_observed_date


def advance_state(
    prior: IngestionState,
    plan: FetchInstruction,
    *,
    committed_at_utc: datetime,
    authoritative_bounds: ObservationBounds,
    fetched_rows: int,
    accepted_rows: int,
    changed_rows: int,
    durable_bronze: bool,
    durable_success_manifest: bool,
) -> IngestionState:
    """Advance only after the complete Bronze + success-manifest durability barrier."""
    if not durable_bronze or not durable_success_manifest:
        return prior
    for name, value in (
        ("fetched_rows", fetched_rows),
        ("accepted_rows", accepted_rows),
        ("changed_rows", changed_rows),
    ):
        if value < 0:
            raise ValueError(f"{name} must be >= 0")
    latest = authoritative_bounds.maximum
    reconcile_time = (
        committed_at_utc if plan.mode is OperationMode.RECONCILE else prior.last_reconcile_utc
    )
    return replace(
        prior,
        last_success_utc=committed_at_utc,
        last_observed_date=latest,
        last_requested_start=plan.filter_start or plan.request_start,
        last_requested_end=plan.request_end,
        mode=plan.mode,
        fetched_row_count=fetched_rows,
        accepted_row_count=accepted_rows,
        changed_row_count=changed_rows,
        last_reconcile_utc=reconcile_time,
    )
