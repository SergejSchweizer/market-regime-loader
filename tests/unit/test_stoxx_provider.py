from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl
import pytest

from application.errors import ProviderHttpError
from application.ports.http import HttpRequest, HttpResponse, RequestContext
from application.ports.market_data import ProviderRequest
from application.registry import series_contract
from ingestion.stoxx_provider import StoxxProvider

NOW = datetime(2026, 8, 19, 2, tzinfo=UTC)
PAYLOAD = b"DATE;V2TX\n2026-08-10;18.0\n2026-08-11;19.0\n2026-08-19;20.0\n"


class FakeTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.calls: list[tuple[HttpRequest, RequestContext]] = []

    def send(self, request: HttpRequest, *, context: RequestContext) -> HttpResponse:
        self.calls.append((request, context))
        return self.response


def request(operation: str = "update") -> ProviderRequest:
    if operation == "update":
        return ProviderRequest("update", date(2026, 8, 11), date(2026, 8, 19), False)
    return ProviderRequest(operation, None, date(2026, 8, 19), True)  # type: ignore[arg-type]


def test_vstoxx_scalar_schema_and_strict_delta_filter() -> None:
    transport = FakeTransport(HttpResponse(200, PAYLOAD, {}))
    provider = StoxxProvider(transport, clock=lambda: NOW)
    frame = provider.fetch(series_contract("vstoxx"), request())
    assert frame.columns == [
        "series_id",
        "provider",
        "observation_date",
        "fetched_at_utc",
        "source_id",
        "source_url",
        "value",
    ]
    assert frame.get_column("observation_date").to_list() == [
        date(2026, 8, 11),
        date(2026, 8, 19),
    ]
    assert frame.get_column("value").dtype == pl.Float64
    assert frame.get_column("source_id").unique().item() == "V2TX"
    assert transport.calls[0][0].params == {}


def test_bootstrap_and_reconcile_accept_full_history() -> None:
    provider = StoxxProvider(FakeTransport(HttpResponse(200, PAYLOAD, {})), clock=lambda: NOW)
    assert provider.fetch(series_contract("vstoxx"), request("bootstrap")).height == 3
    assert provider.fetch(series_contract("vstoxx"), request("reconcile")).height == 3


def test_only_registered_vstoxx_contract_is_accepted() -> None:
    provider = StoxxProvider(FakeTransport(HttpResponse(200, PAYLOAD, {})), clock=lambda: NOW)
    with pytest.raises(ValueError, match="unsupported STOXX"):
        provider.fetch(series_contract("vix"), request())
    with pytest.raises(ValueError, match="bounded logical"):
        provider.fetch(
            series_contract("vstoxx"),
            ProviderRequest("update", date(2026, 8, 11), date(2026, 8, 19), True),
        )


@pytest.mark.parametrize(
    "payload, error",
    [
        (b"DATE;WRONG\n2026-08-19;1\n", "missing date or V2TX"),
        (b"DATE;V2TX\nbad;1\n", "invalid observation"),
        (b"DATE;V2TX\n2026-08-19;bad\n", "missing/non-numeric"),
        (b"DATE;V2TX\n2026-08-19;nan\n", "non-finite"),
        (
            b"DATE;V2TX\n2026-08-19;1\n2026-08-19;2\n",
            "duplicate observation",
        ),
    ],
)
def test_invalid_payloads_are_rejected(payload: bytes, error: str) -> None:
    provider = StoxxProvider(FakeTransport(HttpResponse(200, payload, {})), clock=lambda: NOW)
    with pytest.raises(ValueError, match=error):
        provider.fetch(series_contract("vstoxx"), request())


def test_shortened_source_stays_short_and_revision_value_is_preserved() -> None:
    short = b"DATE;V2TX\n2026-08-19;99.5\n"
    provider = StoxxProvider(FakeTransport(HttpResponse(200, short, {})), clock=lambda: NOW)
    frame = provider.fetch(series_contract("vstoxx"), request())
    assert frame.height == 1
    assert frame.get_column("value").item() == 99.5


def test_http_failure_and_naive_clock_fail_safely() -> None:
    provider = StoxxProvider(FakeTransport(HttpResponse(503, b"", {})), clock=lambda: NOW)
    with pytest.raises(ProviderHttpError) as captured:
        provider.fetch(series_contract("vstoxx"), request())
    assert captured.value.status_code == 503
    naive = StoxxProvider(
        FakeTransport(HttpResponse(200, PAYLOAD, {})),
        clock=lambda: datetime(2026, 8, 19, 2),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        naive.fetch(series_contract("vstoxx"), request())
