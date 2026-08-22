from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from application.gold_catalog import GoldBuildStatus, GoldCatalogRecord
from application.gold_frame import GOLD_COLUMNS
from application.postgres_delta import source_rows_and_digests
from application.postgres_sync import (
    POSTGRES_DATASET_ID,
    GoldDeltaPlan,
    GoldRowDigest,
    GoldSyncState,
    GoldTargetSummary,
)
from application.postgres_sync_service import (
    GoldPostgresDeltaSync,
    GoldSyncCompatibilityError,
    GoldSyncSourceError,
    GoldSyncVerificationError,
)

_BASE = datetime(2026, 1, 1, tzinfo=UTC)
_PATH = "versions/build_id=20260822T100000Z/data.parquet"


def _ts(index: int) -> datetime:
    return _BASE + timedelta(days=index)


def _frame(indices: tuple[int, ...]) -> pl.DataFrame:
    data: dict[str, list[object]] = {"timestamp_m1": [_ts(index) for index in indices]}
    for column_index, column in enumerate(GOLD_COLUMNS[1:], start=1):
        data[column] = [float(index + column_index) for index in indices]
    return pl.DataFrame(data).with_columns(
        pl.col("timestamp_m1").cast(pl.Datetime("us", "UTC"))
    )


def _change(frame: pl.DataFrame, index: int, amount: float = 1000.0) -> pl.DataFrame:
    feature = GOLD_COLUMNS[1]
    return frame.with_columns(
        pl.when(pl.col("timestamp_m1") == _ts(index))
        .then(pl.col(feature) + amount)
        .otherwise(pl.col(feature))
        .alias(feature)
    )


def _record(
    frame: pl.DataFrame,
    *,
    build_id: str = "20260822T100000Z",
    schema_version: int = 1,
    feature_version: int = 1,
) -> GoldCatalogRecord:
    timestamps = frame.get_column("timestamp_m1")
    return GoldCatalogRecord(
        dataset_id=POSTGRES_DATASET_ID,
        build_id=build_id,
        status=GoldBuildStatus.COMPLETE,
        current=True,
        started_at_utc=datetime(2026, 8, 22, 9, tzinfo=UTC),
        completed_at_utc=datetime(2026, 8, 22, 10, tzinfo=UTC),
        schema_version=schema_version,
        feature_version=feature_version,
        min_timestamp=timestamps.min(),
        max_timestamp=timestamps.max(),
        row_count=frame.height,
        data_path=_PATH,
        build_manifest_path="versions/build_id=20260822T100000Z/manifest.json",
        plot_path="versions/build_id=20260822T100000Z/feature_profile.png",
        pruned_at_utc=None,
    )


def _state(
    frame: pl.DataFrame,
    *,
    data_sha256: str = "a" * 64,
    build_id: str = "20260815T100000Z",
    schema_version: int = 1,
    feature_version: int = 1,
) -> GoldSyncState:
    timestamps = frame.get_column("timestamp_m1")
    return GoldSyncState(
        dataset_id=POSTGRES_DATASET_ID,
        source_build_id=build_id,
        data_sha256=data_sha256,
        schema_version=schema_version,
        feature_version=feature_version,
        row_count=frame.height,
        min_timestamp=timestamps.min(),
        max_timestamp=timestamps.max(),
        synced_at_utc=datetime(2026, 8, 15, 10, tzinfo=UTC),
    )


class FakeCatalog:
    def __init__(self, record: GoldCatalogRecord) -> None:
        self.record = record
        self.reads = 0

    def read(self) -> list[GoldCatalogRecord]:
        self.reads += 1
        return [self.record]


class FakeSource:
    def __init__(self, frame: pl.DataFrame, sha256: str = "b" * 64) -> None:
        self.frame = frame
        self.sha256 = sha256
        self.hash_paths: list[str] = []
        self.read_paths: list[str] = []

    def sha256_path(self, relative_data_path: str) -> str:
        self.hash_paths.append(relative_data_path)
        return self.sha256

    def read_path(self, relative_data_path: str) -> pl.DataFrame:
        self.read_paths.append(relative_data_path)
        return self.frame


class FakeRepository:
    def __init__(
        self,
        *,
        state: GoldSyncState | None = None,
        digests: tuple[GoldRowDigest, ...] = (),
        fail_apply: bool = False,
    ) -> None:
        self.state = state
        self.digests = digests
        self.fail_apply = fail_apply
        self.events: list[str] = []
        self.applied: list[tuple[GoldDeltaPlan, GoldSyncState]] = []

    def ensure_schema(self) -> None:
        self.events.append("ensure_schema")

    def read_state(self, dataset_id: str) -> GoldSyncState | None:
        assert dataset_id == POSTGRES_DATASET_ID
        self.events.append("read_state")
        return self.state

    def read_digests(self, dataset_id: str) -> tuple[GoldRowDigest, ...]:
        assert dataset_id == POSTGRES_DATASET_ID
        self.events.append("read_digests")
        return self.digests

    def apply_delta(
        self,
        dataset_id: str,
        plan: GoldDeltaPlan,
        state: GoldSyncState,
    ) -> None:
        assert dataset_id == POSTGRES_DATASET_ID
        self.events.append("apply_delta")
        if self.fail_apply:
            raise RuntimeError("verification failed")
        self.applied.append((plan, state))
        if plan.source_digests:
            self.digests = plan.source_digests
        self.state = state

    def summary(self, dataset_id: str) -> GoldTargetSummary:
        assert dataset_id == POSTGRES_DATASET_ID
        if self.state is None:
            return GoldTargetSummary(0, None, None)
        return GoldTargetSummary(
            self.state.row_count,
            self.state.min_timestamp,
            self.state.max_timestamp,
        )


def _service(
    frame: pl.DataFrame,
    repository: FakeRepository,
    *,
    sha256: str = "b" * 64,
    record: GoldCatalogRecord | None = None,
) -> tuple[GoldPostgresDeltaSync, FakeCatalog, FakeSource]:
    catalog = FakeCatalog(_record(frame) if record is None else record)
    source = FakeSource(frame, sha256)
    service = GoldPostgresDeltaSync(
        catalog=catalog,
        source=source,
        repository=repository,
        clock=lambda: datetime(2026, 8, 22, 12, tzinfo=UTC),
    )
    return service, catalog, source


def test_first_sync_inserts_complete_current_gold() -> None:
    frame = _frame((0, 1, 2))
    repository = FakeRepository()
    service, catalog, source = _service(frame, repository)

    result = service.sync()

    assert (result.inserted, result.updated, result.deleted, result.unchanged) == (3, 0, 0, 0)
    assert result.source_build_id == "20260822T100000Z"
    plan, state = repository.applied[0]
    assert [row.timestamp_m1 for row in plan.inserts] == [_ts(0), _ts(1), _ts(2)]
    assert state.source_build_id == result.source_build_id
    assert repository.state == state
    assert catalog.reads == 1
    assert source.hash_paths == [_PATH]
    assert source.read_paths == [_PATH]


def test_same_complete_data_advances_checkpoint_without_gold_or_digest_mutations() -> None:
    frame = _frame((0, 1, 2))
    _, digests = source_rows_and_digests(frame)
    prior = _state(frame, data_sha256="b" * 64)
    repository = FakeRepository(state=prior, digests=digests)
    service, _, source = _service(frame, repository, sha256="b" * 64)

    result = service.sync()

    assert (result.inserted, result.updated, result.deleted, result.unchanged) == (0, 0, 0, 3)
    plan, state = repository.applied[0]
    assert (plan.inserts, plan.updates, plan.deletes, plan.source_digests) == ((), (), (), ())
    assert state.source_build_id == "20260822T100000Z"
    assert source.read_paths == []


def test_mixed_delta_submits_exactly_two_insert_one_update_one_delete_and_100_unchanged() -> None:
    current = _frame(tuple(range(103)))
    target = _change(_frame((*range(101), 200)), 100)
    _, target_digests = source_rows_and_digests(target)
    repository = FakeRepository(state=_state(target), digests=target_digests)
    service, _, _ = _service(current, repository)

    result = service.sync()

    assert (result.inserted, result.updated, result.deleted, result.unchanged) == (2, 1, 1, 100)
    plan, _ = repository.applied[0]
    assert [row.timestamp_m1 for row in plan.inserts] == [_ts(101), _ts(102)]
    assert [row.timestamp_m1 for row in plan.updates] == [_ts(100)]
    assert plan.deletes == (_ts(200),)
    assert len(plan.unchanged) == 100


def test_multiple_missed_weekly_runs_are_caught_up_in_one_sync() -> None:
    target = _frame((0,))
    current = _frame((0, 7, 14, 21, 28))
    _, target_digests = source_rows_and_digests(target)
    repository = FakeRepository(state=_state(target), digests=target_digests)
    service, _, _ = _service(current, repository)

    result = service.sync()

    assert (result.inserted, result.updated, result.deleted, result.unchanged) == (4, 0, 0, 1)


def test_historical_revision_is_one_update_independent_of_timestamp_watermark() -> None:
    target = _frame((0, 1, 2))
    current = _change(target, 0)
    _, target_digests = source_rows_and_digests(target)
    repository = FakeRepository(state=_state(target), digests=target_digests)
    service, _, _ = _service(current, repository)

    result = service.sync()

    assert (result.inserted, result.updated, result.deleted, result.unchanged) == (0, 1, 0, 2)
    assert repository.applied[0][0].updates[0].timestamp_m1 == _ts(0)


def test_existing_incompatible_serving_state_fails_before_gold_read_or_write() -> None:
    frame = _frame((0, 1))
    _, digests = source_rows_and_digests(frame)
    repository = FakeRepository(
        state=_state(frame, schema_version=2),
        digests=digests,
    )
    service, _, source = _service(frame, repository)

    with pytest.raises(GoldSyncCompatibilityError, match="semantic versions"):
        service.sync()

    assert source.read_paths == []
    assert repository.applied == []


def test_orphan_digest_state_and_digest_count_drift_fail_closed() -> None:
    frame = _frame((0, 1))
    _, digests = source_rows_and_digests(frame)
    service, _, _ = _service(frame, FakeRepository(digests=digests))
    with pytest.raises(GoldSyncVerificationError, match="without authoritative"):
        service.sync()

    repository = FakeRepository(state=_state(frame), digests=digests[:1])
    service, _, _ = _service(frame, repository)
    with pytest.raises(GoldSyncVerificationError, match="digest count"):
        service.sync()


def test_catalog_metadata_mismatch_fails_before_repository_mutation() -> None:
    frame = _frame((0, 1, 2))
    record = _record(frame)
    bad_record = GoldCatalogRecord(
        **{**record.__dict__, "row_count": 2}  # type: ignore[arg-type]
    )
    repository = FakeRepository()
    service, _, _ = _service(frame, repository, record=bad_record)

    with pytest.raises(GoldSyncSourceError, match="row count"):
        service.sync()

    assert repository.applied == []


def test_failed_apply_does_not_claim_new_state_and_retry_converges() -> None:
    frame = _frame((0, 1, 2))
    repository = FakeRepository(fail_apply=True)
    service, _, _ = _service(frame, repository)

    with pytest.raises(RuntimeError, match="verification failed"):
        service.sync()
    assert repository.state is None
    assert repository.applied == []

    repository.fail_apply = False
    result = service.sync()
    assert result.inserted == 3
    assert repository.state is not None


def test_invalid_gold_hash_and_naive_clock_fail_without_success() -> None:
    frame = _frame((0,))
    repository = FakeRepository()
    service, _, _ = _service(frame, repository, sha256="invalid")
    with pytest.raises(GoldSyncSourceError, match="SHA-256"):
        service.sync()

    catalog = FakeCatalog(_record(frame))
    source = FakeSource(frame)
    naive_clock_service = GoldPostgresDeltaSync(
        catalog=catalog,
        source=source,
        repository=FakeRepository(),
        clock=lambda: datetime(2026, 8, 22, 12),
    )
    with pytest.raises(GoldSyncSourceError, match="timezone-aware"):
        naive_clock_service.sync()
