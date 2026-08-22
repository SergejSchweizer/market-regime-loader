"""Read-only filesystem Adapter for catalog-selected immutable Gold sync input."""

from __future__ import annotations

import hashlib
from pathlib import Path

import polars as pl

from application.paths import LakePaths
from ingestion.gold_build_store import GoldBuildStore


class FilesystemGoldFrameSource:
    """Resolve only paths contained by the canonical Gold dataset root."""

    def __init__(self, paths: LakePaths, build_store: GoldBuildStore) -> None:
        self._paths = paths
        self._build_store = build_store

    def sha256_path(self, relative_data_path: str) -> str:
        path = self._resolve(relative_data_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def read_path(self, relative_data_path: str) -> pl.DataFrame:
        return self._build_store.read_path(self._resolve(relative_data_path))

    def _resolve(self, relative_data_path: str) -> Path:
        relative = Path(relative_data_path)
        if relative.is_absolute():
            raise ValueError("Gold sync data path must be relative to the Gold dataset root")
        root = self._paths.gold_dataset_root().resolve()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("Gold sync data path escapes the Gold dataset root") from exc
        return candidate
