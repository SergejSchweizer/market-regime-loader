"""Application-facing HTTP transport contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from application.contracts import Provider


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Safe identity attached to one provider request."""

    provider: Provider
    series_id: str
    source_id: str


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """Provider-built request independent from a concrete HTTP library."""

    method: str
    url: str
    params: Mapping[str, str | int | float] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Minimal response consumed by provider adapters."""

    status_code: int
    content: bytes
    headers: Mapping[str, str]


class HttpTransport(Protocol):
    """Substitutable application-facing HTTP transport."""

    def send(self, request: HttpRequest, *, context: RequestContext) -> HttpResponse:
        """Execute one request using the transport policy."""
        ...


class Sleeper(Protocol):
    """Injectable sleep boundary used by retry behavior."""

    def __call__(self, seconds: float) -> None:
        """Sleep for the requested duration."""
        ...
