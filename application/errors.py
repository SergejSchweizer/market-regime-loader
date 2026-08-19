"""Sanitized application error types."""

from __future__ import annotations

from dataclasses import dataclass

from application.ports.http import RequestContext


@dataclass(frozen=True, slots=True)
class ProviderHttpError(RuntimeError):
    """Provider request failure containing only non-secret diagnostics."""

    context: RequestContext
    category: str
    request_path: str
    status_code: int | None = None

    def __str__(self) -> str:
        status = "" if self.status_code is None else f" status={self.status_code}"
        return (
            f"provider={self.context.provider.value} series={self.context.series_id} "
            f"source={self.context.source_id} category={self.category}{status} "
            f"request={self.request_path}"
        )
