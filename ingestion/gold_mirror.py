"""Rsync adapter for a post-publication Gold mirror."""

from __future__ import annotations

import subprocess
from pathlib import Path


class RsyncGoldMirror:
    def __init__(self, source_root: Path, destination_root: Path) -> None:
        self._source_root = source_root
        self._destination_root = destination_root

    def sync(self) -> None:
        self._destination_root.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "rsync",
                "-aH",
                "--delete-delay",
                "--partial",
                f"{self._source_root}/",
                f"{self._destination_root}/",
            ],
            check=True,
        )
