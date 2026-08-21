from __future__ import annotations

from pathlib import Path

import pytest

from scripts.export_cron_config import export


def test_export_cron_config_quotes_required_runtime_values(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """runtime:
  home: /home/a
  path: /bin
  project_root: /project path
  lake_root: /lake
  log_path: /log
  ssl_cert_file: /cert
  gold_mirror_root: /mirror
secrets:
  fred_api_key: secret key
""",
        encoding="utf-8",
    )
    output = export(config)
    assert "export FRED_API_KEY='secret key'" in output
    assert "export PROJECT_ROOT='/project path'" in output


def test_export_cron_config_rejects_missing_values(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("runtime: {}\nsecrets: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fred_api_key"):
        export(config)
