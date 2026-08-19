"""Operational CLI composition root for market-regime-loader."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TextIO

from api.inventory import render_json, render_text
from application.bronze_orchestration import BronzeOrchestrator
from application.contracts import Provider
from application.daily_pipeline import DailyMedallionPipeline, ProviderBatchError
from application.gold_publication import GoldPublisher
from application.gold_retention import GoldRetentionService
from application.gold_sidecars import GoldSidecarBuilder
from application.paths import LakePaths
from application.planner import PlannerConfig
from application.ports.market_data import MarketDataProvider
from application.registry import SERIES_REGISTRY
from ingestion.bronze_uow import FilesystemBronzeUnitOfWork
from ingestion.cboe_provider import CboeProvider
from ingestion.ecb_provider import EcbProvider
from ingestion.fred_provider import FredProvider
from ingestion.gold_build_store import GoldBuildStore
from ingestion.gold_catalog_repository import GoldCatalogRepository
from ingestion.gold_materialized_views import GoldMaterializedViewWriter
from ingestion.gold_publication_adapters import GoldBundleAdapter
from ingestion.gold_retention_store import GoldBundleSweeper
from ingestion.gold_sidecar_store import GoldSidecarStore
from ingestion.httpx_adapter import HttpxTransport
from ingestion.inventory_refresh import InventoryRefreshService
from ingestion.operational_repository import read_inventory
from ingestion.silver_repository import SilverSeriesRepository
from ingestion.stoxx_provider import StoxxProvider
from ingestion.yahoo_provider import YahooMoveProvider

EXIT_SUCCESS = 0
EXIT_INPUT = 2
EXIT_PROVIDER = 10
EXIT_PIPELINE = 20
_SOURCE_COMMANDS = frozenset({"bootstrap", "update", "reconcile", "run-daily"})
_GOLD_COMMANDS = frozenset({"gold-build", "run-daily"})
_UNUSED_GIT_IDENTITY = "0" * 40


class JsonEventSink:
    """Structured stdlib logging sink with recursive secret sanitization."""

    def __init__(self, logger: logging.Logger, *, secrets: tuple[str, ...]) -> None:
        self._logger = logger
        self._secrets = tuple(secret for secret in secrets if secret)

    def __call__(self, event: dict[str, object]) -> None:
        sanitized = self._sanitize(event)
        self._logger.info(json.dumps(sanitized, ensure_ascii=True, sort_keys=True))

    def _sanitize(self, value: object) -> object:
        if isinstance(value, str):
            result = value
            for secret in self._secrets:
                result = result.replace(secret, "***")
            return result
        if isinstance(value, dict):
            return {str(key): self._sanitize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._sanitize(item) for item in value]
        return value


@dataclass(slots=True)
class Runtime:
    pipeline: DailyMedallionPipeline
    transport: HttpxTransport
    paths: LakePaths

    def close(self) -> None:
        self.transport.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="market-regime-loader")
    parser.add_argument("--lake-root", type=Path, default=Path("lake"))
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    parser.add_argument("--overlap-days", type=int, default=7)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("bootstrap", "update", "reconcile", "silver-build", "run-daily"):
        child = subparsers.add_parser(command)
        child.add_argument("--series", action="append", default=[])
    subparsers.add_parser("gold-build")
    inventory = subparsers.add_parser("inventory")
    inventory.add_argument("--json", action="store_true", dest="as_json")
    inventory.add_argument("--series", action="append", default=[])
    inventory.add_argument("--provider", action="append", default=[])
    return parser


def _today(value: date | None) -> date:
    return value if value is not None else datetime.now().astimezone().date()


def _git_commit_hash() -> str:
    for name in ("MARKET_REGIME_GIT_COMMIT", "GITHUB_SHA"):
        value = os.environ.get(name, "").strip().lower()
        if value:
            return value
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(
            "Gold-capable runtime requires MARKET_REGIME_GIT_COMMIT or a Git checkout"
        ) from exc
    return result.stdout.strip().lower()


def _logger(stderr: TextIO) -> logging.Logger:
    logger = logging.getLogger("market_regime_loader.cli")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def _required_provider_ids(command: str, series_ids: tuple[str, ...]) -> set[Provider]:
    if command not in _SOURCE_COMMANDS:
        return set()
    selected = series_ids if series_ids else tuple(SERIES_REGISTRY)
    unknown = [series_id for series_id in selected if series_id not in SERIES_REGISTRY]
    if unknown:
        raise ValueError(f"unknown series: {', '.join(sorted(unknown))}")
    return {SERIES_REGISTRY[series_id].provider for series_id in selected}


def build_runtime(
    *,
    lake_root: Path,
    command: str,
    series_ids: tuple[str, ...],
    overlap_days: int,
    stderr: TextIO,
) -> Runtime:
    if overlap_days < 0:
        raise ValueError("--overlap-days must be non-negative")
    paths = LakePaths(lake_root)
    transport = HttpxTransport()
    required = _required_provider_ids(command, series_ids)
    fred_api_key = os.environ.get("FRED_API_KEY", "").strip()
    if Provider.FRED in required and not fred_api_key:
        transport.close()
        raise ValueError("FRED_API_KEY is required for selected FRED source series")
    providers: dict[Provider, MarketDataProvider] = {
        Provider.CBOE: CboeProvider(transport),
        Provider.STOXX: StoxxProvider(transport),
        Provider.YAHOO: YahooMoveProvider(transport),
        Provider.ECB: EcbProvider(transport),
    }
    if fred_api_key:
        providers[Provider.FRED] = FredProvider(transport, api_key=fred_api_key)

    uow = FilesystemBronzeUnitOfWork(paths, secrets=(fred_api_key,))
    bronze = BronzeOrchestrator(
        series_registry=SERIES_REGISTRY,
        providers=providers,
        unit_of_work=uow,
        planner_config=PlannerConfig(overlap_days=overlap_days),
    )
    silver = SilverSeriesRepository(paths)
    inventory = InventoryRefreshService(paths)

    git_hash = _git_commit_hash() if command in _GOLD_COMMANDS else _UNUSED_GIT_IDENTITY
    build_store = GoldBuildStore(paths)
    sidecar_store = GoldSidecarStore(
        paths,
        build_store,
        GoldSidecarBuilder(git_commit_hash=git_hash),
    )
    bundle = GoldBundleAdapter(paths, build_store, sidecar_store)
    catalog = GoldCatalogRepository(paths.gold_manifest_parquet())
    views = GoldMaterializedViewWriter(paths)
    publisher = GoldPublisher(catalog, bundle, views)
    retention = GoldRetentionService(catalog, GoldBundleSweeper(paths), views)
    event_sink = JsonEventSink(_logger(stderr), secrets=(fred_api_key,))
    pipeline = DailyMedallionPipeline(
        series_registry=SERIES_REGISTRY,
        bronze=bronze,
        silver=silver,
        publisher=publisher,
        retention=retention,
        inventory=inventory,
        event_sink=event_sink,
    )
    return Runtime(pipeline=pipeline, transport=transport, paths=paths)


def _dispatch(
    runtime: Runtime,
    args: argparse.Namespace,
    *,
    stdout: TextIO,
) -> int:
    command = str(args.command)
    series = tuple(getattr(args, "series", []))
    today = _today(args.today)
    if command == "bootstrap":
        runtime.pipeline.bootstrap(series, today=today)
    elif command == "update":
        runtime.pipeline.update(series, today=today)
    elif command == "reconcile":
        runtime.pipeline.reconcile(series, today=today)
    elif command == "silver-build":
        runtime.pipeline.silver_build(series)
    elif command == "gold-build":
        runtime.pipeline.gold_build()
    elif command == "run-daily":
        runtime.pipeline.run_daily(series, today=today)
    elif command == "inventory":
        runtime.pipeline.inventory()
        records = read_inventory(runtime.paths.inventory())
        if args.series:
            allowed = set(runtime.pipeline.resolve_series(args.series))
            records = [record for record in records if record.series_id in allowed]
        if args.provider:
            try:
                providers = {Provider(value) for value in args.provider}
            except ValueError as exc:
                raise ValueError("unknown --provider value") from exc
            records = [record for record in records if record.provider in providers]
        stdout.write(render_json(records) if args.as_json else render_text(records))
    else:
        raise AssertionError(f"unhandled command: {command}")
    return EXIT_SUCCESS


def main(
    argv: list[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output = sys.stdout if stdout is None else stdout
    error = sys.stderr if stderr is None else stderr
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else EXIT_INPUT

    series = tuple(getattr(args, "series", []))
    runtime: Runtime | None = None
    try:
        runtime = build_runtime(
            lake_root=args.lake_root,
            command=str(args.command),
            series_ids=series,
            overlap_days=args.overlap_days,
            stderr=error,
        )
        return _dispatch(runtime, args, stdout=output)
    except ProviderBatchError as exc:
        JsonEventSink(_logger(error), secrets=(os.environ.get("FRED_API_KEY", ""),))(
            {
                "command": str(args.command),
                "stage": "command",
                "status": "failed",
                "error_type": type(exc).__name__,
                "failed_series": list(exc.failures),
                "exit_code": EXIT_PROVIDER,
            }
        )
        return EXIT_PROVIDER
    except ValueError as exc:
        JsonEventSink(_logger(error), secrets=(os.environ.get("FRED_API_KEY", ""),))(
            {
                "command": str(args.command),
                "stage": "configuration",
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "exit_code": EXIT_INPUT,
            }
        )
        return EXIT_INPUT
    except Exception as exc:
        JsonEventSink(_logger(error), secrets=(os.environ.get("FRED_API_KEY", ""),))(
            {
                "command": str(args.command),
                "stage": "pipeline",
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "exit_code": EXIT_PIPELINE,
            }
        )
        return EXIT_PIPELINE
    finally:
        if runtime is not None:
            runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
