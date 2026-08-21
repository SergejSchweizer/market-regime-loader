from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ingestion.gold_mirror import RsyncGoldMirror


def test_rsync_gold_mirror_syncs_a_complete_directory_tree(tmp_path: Path) -> None:
    source = tmp_path / "lake" / "gold"
    source.mkdir(parents=True)
    destination = tmp_path / "mirror"

    with patch("ingestion.gold_mirror.subprocess.run") as run:
        RsyncGoldMirror(source, destination).sync()

    assert destination.is_dir()
    assert run.call_args.args[0] == [
        "rsync",
        "-aH",
        "--delete-delay",
        "--partial",
        f"{source}/",
        f"{destination}/",
    ]
    assert run.call_args.kwargs == {"check": True}
