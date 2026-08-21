"""STOXX full-file adapter for the registered VSTOXX series."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO

import polars as pl

from application.contracts import FetchCapability, NativeShape, Provider, SeriesContract
from application.errors import ProviderHttpError
from application.ports.http import HttpRequest, HttpTransport, RequestContext
from application.ports.market_data import ProviderRequest

Clock = Callable[[], datetime]
_DEFAULT_SOURCE_URL = "https://www.stoxx.com/document/Indices/Current/HistoricalData/h_v2tx.txt"


def _system_utc_now() -> datetime:
    return datetime.now(UTC)


def _delimiter(content: bytes) -> str:
    first = content.splitlines()[0] if content.splitlines() else b""
    if first.count(b";") >= 1:
        return ";"
    if first.count(b"\t") >= 1:
        return "\t"
    return ","


def _date_expr(column: str) -> pl.Expr:
    text = pl.col(column).cast(pl.String)
    return (
        text.str.strptime(pl.Date, "%Y-%m-%d", strict=False)
        .fill_null(text.str.strptime(pl.Date, "%d.%m.%Y", strict=False))
        .fill_null(text.str.strptime(pl.Date, "%d/%m/%Y", strict=False))
    )


class StoxxProvider:
    """Adapter translating the V2TX full-history source into scalar Bronze."""

    def __init__(
        self,
        transport: HttpTransport,
        *,
        clock: Clock | None = None,
        source_url: str = _DEFAULT_SOURCE_URL,
    ) -> None:
        self._transport = transport
        self._clock = clock if clock is not None else _system_utc_now
        self._source_url = source_url

    @property
    def provider(self) -> Provider:
        return Provider.STOXX

    def fetch(self, series: SeriesContract, request: ProviderRequest) -> pl.DataFrame:
        self._validate_contract(series)
        context = RequestContext(self.provider, series.series_id, series.source_id)
        response = self._transport.send(HttpRequest("GET", self._source_url), context=context)
        if response.status_code != 200:
            raise ProviderHttpError(
                context=context,
                category="source_unavailable",
                request_path=self._source_url,
                status_code=response.status_code,
            )
        frame = self._parse(series, response.content)
        if request.operation == "update":
            if request.maximum_history or request.logical_start is None:
                raise ValueError("STOXX update requires bounded logical delta semantics")
            frame = frame.filter(
                pl.col("observation_date").is_between(
                    request.logical_start,
                    request.logical_end,
                    closed="both",
                )
            )
        return frame.sort("observation_date")

    def _validate_contract(self, series: SeriesContract) -> None:
        if series.provider is not self.provider or series.series_id != "vstoxx":
            raise ValueError("unsupported STOXX series contract")
        if series.source_id != "V2TX":
            raise ValueError("VSTOXX source identity must be V2TX")
        if series.native_shape is not NativeShape.SCALAR:
            raise ValueError("VSTOXX must use scalar Bronze shape")
        if series.fetch_capability is not FetchCapability.FULL_FILE:
            raise ValueError("VSTOXX must use full_file capability")

    def _parse(self, series: SeriesContract, content: bytes) -> pl.DataFrame:
        try:
            raw = pl.read_csv(
                BytesIO(content), separator=_delimiter(content), infer_schema_length=1000
            )
        except Exception as exc:
            raise ValueError("invalid STOXX V2TX payload") from exc
        normalized = {name: name.strip().upper() for name in raw.columns}
        raw = raw.rename(normalized)
        date_column = next(
            (candidate for candidate in ("DATE", "TIME_PERIOD") if candidate in raw.columns),
            None,
        )
        value_column = next(
            (
                candidate
                for candidate in ("V2TX", "OBS_VALUE", "VALUE", "INDEXVALUE", "CLOSE")
                if candidate in raw.columns
            ),
            None,
        )
        if date_column is None or value_column is None:
            raise ValueError("STOXX payload is missing date or V2TX value")
        frame = raw.select(
            _date_expr(date_column).alias("observation_date"),
            pl.col(value_column).cast(pl.Float64, strict=False).alias("value"),
        )
        if bool(frame.select(pl.col("observation_date").is_null().any()).item()):
            raise ValueError("STOXX payload contains invalid observation dates")
        if bool(frame.select(pl.col("value").is_null().any()).item()):
            raise ValueError("STOXX payload contains missing/non-numeric values")
        if not bool(frame.select(pl.col("value").is_finite().all()).item()):
            raise ValueError("STOXX payload contains non-finite values")
        if bool(frame.select(pl.col("observation_date").is_duplicated().any()).item()):
            raise ValueError("STOXX payload contains duplicate observation dates")
        fetched_at = self._clock()
        if fetched_at.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        fetched_at = fetched_at.astimezone(UTC)
        return frame.with_columns(
            pl.lit(series.series_id).alias("series_id"),
            pl.lit(self.provider.value).alias("provider"),
            pl.lit(fetched_at).alias("fetched_at_utc"),
            pl.lit(series.source_id).alias("source_id"),
            pl.lit(self._source_url).alias("source_url"),
        ).select(
            "series_id",
            "provider",
            "observation_date",
            "fetched_at_utc",
            "source_id",
            "source_url",
            "value",
        )
