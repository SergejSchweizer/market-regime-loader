"""Provider adapter protocol shared by orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

import polars as pl

from application.contracts import Provider, SeriesContract

ProviderOperation = Literal["bootstrap", "update", "reconcile"]


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """Provider-neutral operation and logical observation window."""

    operation: ProviderOperation
    logical_start: date | None
    logical_end: date
    maximum_history: bool

    def __post_init__(self) -> None:
        if self.logical_start is not None and self.logical_start > self.logical_end:
            raise ValueError("logical_start cannot be after logical_end")
        if self.operation == "update" and self.logical_start is None:
            raise ValueError("update requires a bounded logical_start")
        if self.operation != "update" and not self.maximum_history:
            raise ValueError("bootstrap/reconcile require maximum_history")


class MarketDataProvider(Protocol):
    """Common provider contract without coupling application to implementations."""

    @property
    def provider(self) -> Provider:
        """Return canonical provider identity."""
        ...

    def fetch(self, series: SeriesContract, request: ProviderRequest) -> pl.DataFrame:
        """Fetch one series while honoring the exact logical request contract."""
        ...
