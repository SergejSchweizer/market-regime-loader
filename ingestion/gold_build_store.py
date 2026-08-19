"""Creation-only immutable Parquet storage for canonical Gold builds."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import polars as pl

from application.gold_frame import GOLD_COLUMNS
from application.paths import LakePaths

Clock = Callable[[], datetime]
FaultInjector = Callable[[str], None]


def _system_utc_now() -> datetime:
    return datetime.now(UTC)


def _no_fault(stage: str) -> None:
    del stage


def _gold_schema() -> pl.Schema:
    return pl.Schema(
        {
            "timestamp_m1": pl.Datetime("us", "UTC"),
            **{column: pl.Float64() for column in GOLD_COLUMNS[1:]},
        }
    )


@dataclass(frozen=True, slots=True)
class GoldBuildArtifact:
    """Immutable build artifact identity returned to sidecar/publication layers."""

    build_id: str
    data_path: Path
    data_sha256: str
    row_count: int
    min_timestamp: datetime | None
    max_timestamp: datetime | None


class GoldBuildStore:
    """Repository/Adapter that writes and reads explicit immutable Gold Parquet builds."""

    def __init__(
        self,
        paths: LakePaths,
        *,
        clock: Clock | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self._paths = paths
        self._clock = clock if clock is not None else _system_utc_now
        self._fault = fault_injector if fault_injector is not None else _no_fault

    def next_build_id(self) -> str:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("Gold build clock must be timezone-aware")
        return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

    def build_dir(self, build_id: str) -> Path:
        return self._paths.gold_build_dir(build_id)

    def data_path(self, build_id: str) -> Path:
        return self._paths.gold_build_data(build_id)

    def create(self, frame: pl.DataFrame, *, build_id: str | None = None) -> GoldBuildArtifact:
        """Create exactly one immutable build; an existing build id is a hard collision."""
        self._validate_frame(frame)
        resolved_id = self.next_build_id() if build_id is None else build_id
        self._validate_build_id(resolved_id)
        build_dir = self.build_dir(resolved_id)
        data_path = self.data_path(resolved_id)
        versions_dir = build_dir.parent
        versions_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.mkdir(build_dir)
        except FileExistsError as exc:
            raise FileExistsError(f"Gold build already exists: {resolved_id}") from exc

        temp_path: Path | None = None
        try:
            self._fault("after_directory")
            buffer = BytesIO()
            frame.write_parquet(buffer)
            payload = buffer.getvalue()
            data_sha256 = hashlib.sha256(payload).hexdigest()
            descriptor, temp_name = tempfile.mkstemp(
                dir=build_dir,
                prefix=".data.parquet.",
                suffix=".tmp",
            )
            temp_path = Path(temp_name)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            self._fault("after_temp")
            os.replace(temp_path, data_path)
            temp_path = None
            self._fault("after_replace")
            reread = pl.read_parquet(data_path)
            self._validate_frame(reread)
            if hashlib.sha256(data_path.read_bytes()).hexdigest() != data_sha256:
                raise IOError("Gold data SHA-256 mismatch after durable write")
            timestamps = reread.get_column("timestamp_m1")
            minimum = timestamps.min()
            maximum = timestamps.max()
            if minimum is not None and not isinstance(minimum, datetime):
                raise TypeError("Gold min timestamp must be datetime")
            if maximum is not None and not isinstance(maximum, datetime):
                raise TypeError("Gold max timestamp must be datetime")
            return GoldBuildArtifact(
                build_id=resolved_id,
                data_path=data_path,
                data_sha256=data_sha256,
                row_count=reread.height,
                min_timestamp=minimum,
                max_timestamp=maximum,
            )
        except BaseException:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            shutil.rmtree(build_dir, ignore_errors=True)
            raise

    def read_build(self, build_id: str) -> pl.DataFrame:
        """Read exactly the requested build id; never infer newest/current from the filesystem."""
        self._validate_build_id(build_id)
        return self.read_path(self.data_path(build_id))

    def read_path(self, path: Path) -> pl.DataFrame:
        """Read exactly one explicit data path."""
        if not path.is_file():
            raise FileNotFoundError(path)
        frame = pl.read_parquet(path)
        self._validate_frame(frame)
        return frame

    @staticmethod
    def _validate_build_id(build_id: str) -> None:
        try:
            parsed = datetime.strptime(build_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        except ValueError as exc:
            raise ValueError("build_id must match YYYYMMDDTHHMMSSZ") from exc
        if parsed.strftime("%Y%m%dT%H%M%SZ") != build_id:
            raise ValueError("build_id must match YYYYMMDDTHHMMSSZ exactly")

    @staticmethod
    def _validate_frame(frame: pl.DataFrame) -> None:
        expected = _gold_schema()
        if frame.columns != list(GOLD_COLUMNS):
            raise ValueError("Gold frame column order mismatch")
        if frame.schema != expected:
            raise TypeError("Gold frame schema mismatch")
        timestamp = frame.get_column("timestamp_m1")
        if timestamp.null_count():
            raise ValueError("Gold timestamp_m1 cannot be null")
        if bool(timestamp.is_duplicated().any()):
            raise ValueError("Gold timestamp_m1 must be unique")
        if not frame.is_empty() and not frame.sort("timestamp_m1").equals(frame):
            raise ValueError("Gold timestamp_m1 must be strictly increasing")
