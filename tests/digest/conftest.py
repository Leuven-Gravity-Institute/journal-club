"""Fixtures for the digest tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest


@pytest.fixture
def no_sleep() -> Callable[[float], None]:
    """Provide a ``sleep`` that returns at once.

    Returns:
        The fake.
    """
    return lambda _: None
