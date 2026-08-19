from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from application.ports.lake import MonthlyFrameRepository
from ingestion import parquet_repository as repo

SCHEMA = {
    "series_id": pl.String,
    "observation_date": pl.Date,
    "value": pl.Float64,
}


def frame(rows: list[tuple[str, date, float]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=SCHEMA, orient="row")


def month_path(root: Path, day: date) -> Path:
    return root / f"year={day.year:04d}" / f"month={day.month:02d}" / "data.parquet"


def test_repository_implements_protocol() -> None:
    repository: MonthlyFrameRepository = repo.PolarsMonthlyRepository()
    assert repository.read([], sort_by=["observation_date"]).is_empty()


def test_read_zero_one_and_multiple_months_in_key_order(tmp_path: Path) -> None:
    january = month_path(tmp_path, date(2026, 1, 1))
    february = month_path(tmp_path, date(2026, 2, 1))
    repo.atomic_write_parquet(frame([("x", date(2026, 1, 2), 2.0)]), january)
    repo.atomic_write_parquet(frame([("x", date(2026, 2, 2), 3.0)]), february)

    assert repo.read_monthly([], sort_by=["observation_date"]).is_empty()
    assert repo.read_monthly([january], sort_by=["observation_date"]).height == 1
    combined = repo.read_monthly([february, january], sort_by=["observation_date"])
    assert combined.get_column("value").to_list() == [2.0, 3.0]


def test_read_rejects_missing_sort_key(tmp_path: Path) -> None:
    path = tmp_path / "data.parquet"
    frame([("x", date(2026, 1, 2), 2.0)]).write_parquet(path)
    with pytest.raises(ValueError, match="sort key"):
        repo.read_monthly([path], sort_by=["missing"])


def test_observation_bounds_use_only_authoritative_files(tmp_path: Path) -> None:
    first = month_path(tmp_path, date(2000, 1, 1))
    latest = month_path(tmp_path, date(2026, 8, 1))
    repo.atomic_write_parquet(frame([("x", date(2000, 1, 3), 1.0)]), first)
    repo.atomic_write_parquet(frame([("x", date(2026, 8, 18), 2.0)]), latest)
    stale = latest.parent / ".data.parquet.crash.tmp"
    frame([("x", date(2099, 1, 1), 99.0)]).write_parquet(stale)

    bounds = repo.observation_bounds([stale, latest, first])
    assert bounds.minimum == date(2000, 1, 3)
    assert bounds.maximum == date(2099, 1, 1)

    authoritative = repo.observation_bounds([latest, first])
    assert authoritative.minimum == date(2000, 1, 3)
    assert authoritative.maximum == date(2026, 8, 18)


def test_observation_bounds_empty_and_missing_date_column(tmp_path: Path) -> None:
    assert repo.observation_bounds([]).minimum is None
    path = tmp_path / "bad.parquet"
    pl.DataFrame({"value": [1.0]}).write_parquet(path)
    with pytest.raises(ValueError, match="date column"):
        repo.observation_bounds([path])


def test_diff_classifies_insert_unchanged_and_revision() -> None:
    existing = frame(
        [
            ("x", date(2026, 1, 1), 1.0),
            ("x", date(2026, 1, 2), 2.0),
        ]
    )
    incoming = frame(
        [
            ("x", date(2026, 1, 1), 1.0),
            ("x", date(2026, 1, 2), 20.0),
            ("x", date(2026, 1, 3), 3.0),
        ]
    )
    diff = repo.diff_frames(existing, incoming, key=["series_id", "observation_date"])
    assert diff.unchanged.get_column("value").to_list() == [1.0]
    assert diff.revisions.get_column("value").to_list() == [20.0]
    assert diff.inserts.get_column("value").to_list() == [3.0]


def test_diff_rejects_duplicate_incoming_and_schema_mismatch() -> None:
    duplicate = frame(
        [
            ("x", date(2026, 1, 1), 1.0),
            ("x", date(2026, 1, 1), 2.0),
        ]
    )
    with pytest.raises(ValueError, match="duplicate natural keys"):
        repo.diff_frames(pl.DataFrame(schema=SCHEMA), duplicate, key=["series_id", "observation_date"])

    with pytest.raises(ValueError, match="columns must match"):
        repo.diff_frames(
            frame([("x", date(2026, 1, 1), 1.0)]),
            frame([("x", date(2026, 1, 2), 2.0)]).drop("value"),
            key=["series_id", "observation_date"],
        )


def test_merge_is_idempotent_and_revision_replaces_once() -> None:
    existing = frame([("x", date(2026, 1, 1), 1.0)])
    incoming = frame([("x", date(2026, 1, 1), 2.0)])
    merged, diff = repo.merge_frames(existing, incoming, key=["series_id", "observation_date"])
    assert diff.revisions.height == 1
    assert merged.rows() == [("x", date(2026, 1, 1), 2.0)]

    rerun, second = repo.merge_frames(merged, incoming, key=["series_id", "observation_date"])
    assert not second.has_changes
    assert rerun.equals(merged)


def test_atomic_write_replaces_destination_and_removes_temp(tmp_path: Path) -> None:
    destination = tmp_path / "data.parquet"
    repo.atomic_write_parquet(frame([("x", date(2026, 1, 1), 1.0)]), destination)
    repo.atomic_write_parquet(frame([("x", date(2026, 1, 1), 2.0)]), destination)
    assert pl.read_parquet(destination).item(0, "value") == 2.0
    assert not list(tmp_path.glob(".data.parquet.*.tmp"))


def test_atomic_write_failure_preserves_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "data.parquet"
    original = frame([("x", date(2026, 1, 1), 1.0)])
    repo.atomic_write_parquet(original, destination)
    before = destination.read_bytes()

    def fail_replace(source: Path | str, target: Path | str) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(repo.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        repo.atomic_write_parquet(frame([("x", date(2026, 1, 1), 2.0)]), destination)
    assert destination.read_bytes() == before
    assert not list(tmp_path.glob(".data.parquet.*.tmp"))


def test_stale_temp_is_never_discovered_as_authoritative(tmp_path: Path) -> None:
    destination = tmp_path / "data.parquet"
    stale = tmp_path / ".data.parquet.stale.tmp"
    frame([("x", date(2026, 1, 1), 9.0)]).write_parquet(stale)
    assert repo.read_monthly([destination], sort_by=["observation_date"]).is_empty()


def test_monthly_upsert_rewrites_only_affected_month(tmp_path: Path) -> None:
    january_path = month_path(tmp_path, date(2026, 1, 1))
    february_path = month_path(tmp_path, date(2026, 2, 1))
    existing = frame(
        [
            ("x", date(2026, 1, 10), 1.0),
            ("x", date(2026, 2, 10), 2.0),
        ]
    )
    repo.atomic_write_parquet(existing.filter(pl.col("observation_date").dt.month() == 1), january_path)
    repo.atomic_write_parquet(existing.filter(pl.col("observation_date").dt.month() == 2), february_path)
    february_before = february_path.read_bytes()
    february_mtime = os.stat(february_path).st_mtime_ns

    incoming = frame([("x", date(2026, 1, 10), 10.0)])
    _, written = repo.upsert_monthly(
        existing,
        incoming,
        key=["series_id", "observation_date"],
        date_column="observation_date",
        path_for_date=lambda day: month_path(tmp_path, day),
    )
    assert written == (january_path,)
    assert pl.read_parquet(january_path).item(0, "value") == 10.0
    assert february_path.read_bytes() == february_before
    assert os.stat(february_path).st_mtime_ns == february_mtime


def test_monthly_upsert_noop_performs_no_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    existing = frame([("x", date(2026, 1, 10), 1.0)])
    called = False

    def fail_if_called(data: pl.DataFrame, destination: Path) -> None:
        nonlocal called
        called = True
        raise AssertionError("write must not happen")

    monkeypatch.setattr(repo, "atomic_write_parquet", fail_if_called)
    diff, written = repo.upsert_monthly(
        existing,
        existing,
        key=["series_id", "observation_date"],
        date_column="observation_date",
        path_for_date=lambda day: month_path(tmp_path, day),
    )
    assert not diff.has_changes
    assert written == ()
    assert not called
