from __future__ import annotations

import polars as pl
import pytest

from application.parallelism import PolarsExecutionPolicy


def test_all_available_cores_matches_polars_thread_pool() -> None:
    assert PolarsExecutionPolicy.all_available_cores().workers == pl.thread_pool_size()


def test_policy_preserves_input_order_and_rejects_invalid_worker_count() -> None:
    assert PolarsExecutionPolicy(3).map(lambda value: value * 2, (3, 1, 2)) == [6, 2, 4]
    with pytest.raises(ValueError, match="workers"):
        PolarsExecutionPolicy(0)
