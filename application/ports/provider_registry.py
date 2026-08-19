"""Provider adapter registry contracts."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from application.contracts import Provider


class ProviderAdapter(Protocol):
    """Minimum identity exposed by a provider adapter before PR-04."""

    @property
    def provider(self) -> Provider:
        """Return the canonical provider identity."""
        ...


class AdapterRegistry:
    """Registry/Factory that resolves one adapter per provider."""

    def __init__(self, adapters: Iterable[ProviderAdapter]) -> None:
        self._adapters: dict[Provider, ProviderAdapter] = {}
        for adapter in adapters:
            if adapter.provider in self._adapters:
                raise ValueError(f"duplicate adapter for provider: {adapter.provider.value}")
            self._adapters[adapter.provider] = adapter

    def resolve(self, provider: Provider) -> ProviderAdapter:
        """Resolve a registered adapter or fail explicitly."""
        try:
            return self._adapters[provider]
        except KeyError as exc:
            raise KeyError(f"no adapter registered for provider: {provider.value}") from exc
