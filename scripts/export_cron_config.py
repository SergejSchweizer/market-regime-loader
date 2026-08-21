"""Export protected operational YAML configuration as shell-safe environment assignments."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Any

import yaml


def _value(config: dict[str, Any], section: str, key: str) -> str:
    value = config.get(section, {}).get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing {section}.{key} in config.yaml")
    return value


def export(path: Path) -> str:
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("config.yaml must be a mapping")
    values = {
        "FRED_API_KEY": _value(parsed, "secrets", "fred_api_key"),
        "SSL_CERT_FILE": _value(parsed, "runtime", "ssl_cert_file"),
        "MARKET_REGIME_GOLD_MIRROR_ROOT": _value(parsed, "runtime", "gold_mirror_root"),
        "PATH": _value(parsed, "runtime", "path"),
        "HOME": _value(parsed, "runtime", "home"),
        "PROJECT_ROOT": _value(parsed, "runtime", "project_root"),
        "LAKE_ROOT": _value(parsed, "runtime", "lake_root"),
        "LOG_PATH": _value(parsed, "runtime", "log_path"),
    }
    return "\n".join(f"export {name}={shlex.quote(value)}" for name, value in values.items())


def main() -> int:
    try:
        print(export(Path(sys.argv[1])))
    except (IndexError, OSError, ValueError, yaml.YAMLError) as error:
        print(f"config export failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
