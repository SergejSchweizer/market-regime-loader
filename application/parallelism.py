"""Bounded all-core execution policy for independent Polars work units."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TypeVar

import polars as pl

Input = TypeVar("Input")
Output = TypeVar("Output")


@dataclass(frozen=True, slots=True)
class PolarsExecutionPolicy:
    """Run independent work concurrently within Polars' bounded global thread pool."""

    workers: int

    def __post_init__(self) -> None:
        if self.workers < 1:
            raise ValueError("workers must be >= 1")

    @classmethod
    def all_available_cores(cls) -> PolarsExecutionPolicy:
        return cls(pl.thread_pool_size())

    def map(self, function: Callable[[Input], Output], values: Sequence[Input]) -> list[Output]:
        if len(values) < 2:
            return [function(value) for value in values]
        with ThreadPoolExecutor(max_workers=min(self.workers, len(values))) as executor:
            return list(executor.map(function, values))
