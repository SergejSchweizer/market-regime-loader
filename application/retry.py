"""Deterministic retry Strategy for provider HTTP requests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential retry policy."""

    max_attempts: int = 3
    initial_delay_seconds: float = 0.5
    multiplier: float = 2.0
    max_delay_seconds: float = 8.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds must be >= 0")
        if self.multiplier < 1:
            raise ValueError("multiplier must be >= 1")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds must be >= 0")

    @staticmethod
    def retryable_status(status_code: int) -> bool:
        """Return whether an HTTP status is transient by contract."""
        return status_code == 429 or 500 <= status_code <= 599

    def delay_after(self, failed_attempt: int, retry_after: float | None = None) -> float:
        """Return deterministic delay after a failed attempt."""
        if failed_attempt < 1:
            raise ValueError("failed_attempt must be >= 1")
        if retry_after is not None and retry_after >= 0:
            return min(retry_after, self.max_delay_seconds)
        exponential = self.initial_delay_seconds * self.multiplier ** (failed_attempt - 1)
        return min(exponential, self.max_delay_seconds)
