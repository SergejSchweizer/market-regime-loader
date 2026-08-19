"""Provider adapter protocol shared by orchestration."""

from __future__ import annotations

from typing import Protocol

from application.contracts import Provider


class MarketDataProvider(Protocol):
    """Common provider identity without coupling application to implementations."""

    @property
    def provider(self) -> Provider:
        """Return canonical provider identity."""
        ...
