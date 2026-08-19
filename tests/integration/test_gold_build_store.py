from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import pytest

from application.gold_frame import GOLD_COLUMNS
from application.paths import LakePaths
from ingestion.gold_build_store import GoldBuildStore

pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 19, 2, 3, 4, tzinfo=UTC)


def _frame(offset: float = 0.0) -> pl.DataFrame:
    timestamps = [datetime(2026, 8, 18, tzinfo=UTC), datetime(2026, 8, 19, tzinfo=UTC)]
    return pl.DataFrame(
        {
            "timestamp_m1": timestamps,
            **{
                column: [offset + float(index), offset + float(index + 1)]
                for index, column in enumerate(GOLD_COLUMNS[1:])
            },
        },
        schema={
            "timestamp_m1": pl.Datetime("us", "UTC"),
            **{column: pl.Float64 for column in GOLD_COLUMNS[1:]},
        },
    )


def test_build_id_format_roundtrip_hash_and_explicit_read(tmp_path: Path) -> None:
    paths = LakePaths(tmp_path / "lake")
    store = GoldBuildStore(paths, clock=lambda: NOW)
    assert store.next_build_id() == "20260819T020304Z"
    artifact = store.create(_frame())
    assert artifact.build_id == "20260819T020304Z"
    assert artifact.data_path == paths.gold_data(artifact.build_id)
    assert artifact.data_path.is_file()
    assert artifact.data_sha256 == hashlib.sha256(artifact.data_path.read_bytes()).hexdigest()
    assert artifact.row_count == 2
    assert artifact.min_timestamp == datetime(2026, 8, 18, tzinfo=UTC)
    assert artifact.max_timestamp == datetime(2026, 8, 19, tzinfo=UTC)
    assert store.read_build(artifact.build_id).equals(_frame())
    assert store.read_path(artifact.data_path).equals(_frame())


def test_clock_is_normalized_to_utc_and_naive_clock_fails(tmp_path: Path) -> None:
    offset_clock = datetime(2026, 8, 19, 4, 3, 4, tzinfo=timezone(timedelta(hours=2)))
    store = GoldBuildStore(LakePaths(tmp_path / "lake"), clock=lambda: offset_clock)
    assert store.next_build_id() == "20260819T020304Z"
    naive = GoldBuildStore(
        LakePaths(tmp_path / "naive"), clock=lambda: datetime(2026, 8, 19, 2, 3, 4)
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        naive.next_build_id()


def test_collision_is_creation_only_and_preserves_original_bytes(tmp_path: Path) -> None:
    store = GoldBuildStore(LakePaths(tmp_path / "lake"), clock=lambda: NOW)
    first = store.create(_frame())
    original = first.data_path.read_bytes()
    with pytest.raises(FileExistsError, match="already exists"):
        store.create(_frame(100.0))
    assert first.data_path.read_bytes() == original
    assert hashlib.sha256(original).hexdigest() == first.data_sha256


def test_explicit_older_build_read_is_stable_after_newer_exists(tmp_path: Path) -> None:
    paths = LakePaths(tmp_path / "lake")
    store = GoldBuildStore(paths, clock=lambda: NOW)
    older = store.create(_frame(), build_id="20260818T020304Z")
    newer = store.create(_frame(100.0), build_id="20260819T020304Z")
    assert newer.data_path != older.data_path
    assert store.read_build("20260818T020304Z").equals(_frame())
    assert store.read_build("20260819T020304Z").equals(_frame(100.0))


@pytest.mark.parametrize("stage", ["after_directory", "after_temp", "after_replace"])
def test_partial_write_failure_removes_entire_candidate_bundle(tmp_path: Path, stage: str) -> None:
    paths = LakePaths(tmp_path / "lake")

    def fail(current: str) -> None:
        if current == stage:
            raise RuntimeError("injected write failure")

    store = GoldBuildStore(paths, clock=lambda: NOW, fault_injector=fail)
    with pytest.raises(RuntimeError, match="injected write failure"):
        store.create(_frame())
    assert not paths.gold_build_root("20260819T020304Z").exists()


def test_schema_order_timestamp_and_id_validation_fail_closed(tmp_path: Path) -> None:
    store = GoldBuildStore(LakePaths(tmp_path / "lake"), clock=lambda: NOW)
    with pytest.raises(ValueError, match="column order"):
        store.create(_frame().select(list(reversed(GOLD_COLUMNS))))
    with pytest.raises(TypeError, match="schema"):
        store.create(_frame().with_columns(pl.col("vix_level").cast(pl.Int64)))
    duplicate = pl.concat([_frame().head(1), _frame().head(1)])
    with pytest.raises(ValueError, match="unique"):
        store.create(duplicate)
    with pytest.raises(ValueError, match="strictly increasing"):
        store.create(_frame().sort("timestamp_m1", descending=True))
    with pytest.raises(ValueError, match="YYYYMMDDTHHMMSSZ"):
        store.create(_frame(), build_id="bad-id")
    with pytest.raises(FileNotFoundError):
        store.read_build("20260817T020304Z")
