"""Registry-driven Bronze ingestion application service."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

import polars as pl

from application.contracts import Provider, SeriesContract
from application.operational_records import IngestionRunRecord, RunMode, RunStatus
from application.planner import FetchInstruction, OperationMode, PlannerConfig, build_plan
from application.ports.bronze import BronzeUnitOfWork, PreparedBronze
from application.ports.market_data import MarketDataProvider, ProviderRequest
from application.state import advance_state

Clock = Callable[[], datetime]
RunIdFactory = Callable[[str], str]


def _system_utc_now() -> datetime:
    return datetime.now(UTC)


def _default_run_id(series_id: str) -> str:
    return f"{series_id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"


@dataclass(frozen=True, slots=True)
class SeriesRunResult:
    """Stable result returned by one isolated series execution."""

    series_id: str
    run_id: str
    mode: OperationMode
    inserted_rows: int
    revised_rows: int
    written_partitions: int


@dataclass(frozen=True, slots=True)
class BatchRunResult:
    """Per-series isolation result for a multi-series request."""

    successes: tuple[SeriesRunResult, ...]
    failures: tuple[str, ...]


class BronzeOrchestrator:
    """Application service coordinating providers through injected registries and a UoW."""

    def __init__(
        self,
        *,
        series_registry: Mapping[str, SeriesContract],
        providers: Mapping[Provider, MarketDataProvider],
        unit_of_work: BronzeUnitOfWork,
        planner_config: PlannerConfig | None = None,
        clock: Clock | None = None,
        run_id_factory: RunIdFactory | None = None,
    ) -> None:
        self._series_registry = series_registry
        self._providers = providers
        self._uow = unit_of_work
        self._planner_config = planner_config if planner_config is not None else PlannerConfig()
        self._clock = clock if clock is not None else _system_utc_now
        self._run_id_factory = run_id_factory if run_id_factory is not None else _default_run_id

    def run_series(
        self,
        series_id: str,
        *,
        operation: OperationMode = OperationMode.UPDATE,
        today: date,
    ) -> SeriesRunResult:
        contract = self._resolve_series(series_id)
        provider = self._resolve_provider(contract.provider)
        bounds = self._uow.bounds(contract)
        if operation is OperationMode.BOOTSTRAP and bounds.maximum is not None:
            raise ValueError("explicit bootstrap requires empty authoritative Bronze")
        plan = build_plan(
            contract,
            bounds,
            today=today,
            explicit_reconcile=operation is OperationMode.RECONCILE,
            config=self._planner_config,
        )
        if operation is OperationMode.BOOTSTRAP and plan.mode is not OperationMode.BOOTSTRAP:
            raise ValueError("explicit bootstrap did not resolve to bootstrap plan")
        if operation is OperationMode.UPDATE and bounds.maximum is not None:
            if plan.mode is not OperationMode.UPDATE or plan.maximum_history:
                raise AssertionError("normal existing-history call must remain a bounded update")

        run_id = self._run_id_factory(series_id)
        started = self._utc_now()
        fetched_rows = 0
        accepted_rows = 0
        requested_start = plan.filter_start or plan.request_start
        try:
            incoming = provider.fetch(contract, self._provider_request(plan))
            fetched_rows = incoming.height
            accepted = self._enforce_window(incoming, plan)
            accepted_rows = accepted.height
            prepared = self._uow.prepare(contract, accepted)
            completed = self._utc_now()
            success_run = self._success_run(
                run_id=run_id,
                contract=contract,
                plan=plan,
                started=started,
                completed=completed,
                fetched_rows=fetched_rows,
                accepted_rows=accepted_rows,
                prepared=prepared,
            )
            prior = self._uow.state(contract)
            next_state = advance_state(
                prior,
                plan,
                committed_at_utc=completed,
                authoritative_bounds=prepared.post_bounds,
                fetched_rows=fetched_rows,
                accepted_rows=accepted_rows,
                changed_rows=prepared.diff.inserts.height + prepared.diff.revisions.height,
                durable_bronze=True,
                durable_success_manifest=True,
            )
            self._uow.commit_success(prepared, success_run, next_state)
            return SeriesRunResult(
                series_id=series_id,
                run_id=run_id,
                mode=plan.mode,
                inserted_rows=prepared.diff.inserts.height,
                revised_rows=prepared.diff.revisions.height,
                written_partitions=prepared.written_partitions,
            )
        except Exception as exc:
            failed = IngestionRunRecord(
                run_id=run_id,
                provider=contract.provider,
                series_id=contract.series_id,
                mode=RunMode(plan.mode.value),
                requested_start=requested_start,
                requested_end=plan.request_end,
                fetched_rows=fetched_rows,
                accepted_rows=accepted_rows,
                inserted_rows=0,
                revised_rows=0,
                written_partitions=0,
                status=RunStatus.FAILED,
                started_at_utc=started,
                completed_at_utc=self._utc_now(),
                error_category=type(exc).__name__,
                error_message="series ingestion failed",
            )
            self._uow.record_failure(failed)
            raise

    def run_many(
        self,
        series_ids: Sequence[str],
        *,
        operation: OperationMode = OperationMode.UPDATE,
        today: date,
    ) -> BatchRunResult:
        successes: list[SeriesRunResult] = []
        failures: list[str] = []
        for series_id in series_ids:
            try:
                successes.append(self.run_series(series_id, operation=operation, today=today))
            except Exception:
                failures.append(series_id)
        return BatchRunResult(tuple(successes), tuple(failures))

    def _resolve_series(self, series_id: str) -> SeriesContract:
        try:
            return self._series_registry[series_id]
        except KeyError as exc:
            raise KeyError(f"unknown canonical series_id: {series_id}") from exc

    def _resolve_provider(self, provider: Provider) -> MarketDataProvider:
        try:
            return self._providers[provider]
        except KeyError as exc:
            raise KeyError(f"provider adapter not registered: {provider.value}") from exc

    @staticmethod
    def _provider_request(plan: FetchInstruction) -> ProviderRequest:
        return ProviderRequest(
            plan.mode.value,
            plan.filter_start or plan.request_start,
            plan.request_end,
            plan.maximum_history,
        )

    @staticmethod
    def _enforce_window(frame: pl.DataFrame, plan: FetchInstruction) -> pl.DataFrame:
        if plan.mode is not OperationMode.UPDATE or frame.is_empty():
            return frame
        start = plan.filter_start or plan.request_start
        if start is None:
            raise AssertionError("bounded update has no logical start")
        if "observation_date" not in frame.columns:
            raise ValueError("provider frame is missing observation_date")
        outside = frame.filter(
            ~pl.col("observation_date").is_between(start, plan.request_end, closed="both")
        )
        if outside.height:
            raise ValueError("provider returned observations outside logical request window")
        return frame

    @staticmethod
    def _success_run(
        *,
        run_id: str,
        contract: SeriesContract,
        plan: FetchInstruction,
        started: datetime,
        completed: datetime,
        fetched_rows: int,
        accepted_rows: int,
        prepared: PreparedBronze,
    ) -> IngestionRunRecord:
        return IngestionRunRecord(
            run_id=run_id,
            provider=contract.provider,
            series_id=contract.series_id,
            mode=RunMode(plan.mode.value),
            requested_start=plan.filter_start or plan.request_start,
            requested_end=plan.request_end,
            fetched_rows=fetched_rows,
            accepted_rows=accepted_rows,
            inserted_rows=prepared.diff.inserts.height,
            revised_rows=prepared.diff.revisions.height,
            written_partitions=prepared.written_partitions,
            status=RunStatus.SUCCESS,
            started_at_utc=started,
            completed_at_utc=completed,
        )

    def _utc_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return timezone-aware datetime")
        return value.astimezone(UTC)
