"""Retry helper with exponential backoff for transient failures."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_on_exception(
    func: Callable[[], T],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable: tuple[type[BaseException], ...] = (Exception,),
    description: str = "operation",
) -> T:
    """Call *func* with exponential backoff on retryable exceptions.

    Returns the result of a successful call or re-raises the last exception.
    """
    last_exc: BaseException | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except retryable as exc:
            last_exc = exc
            if attempt == max_retries:
                logger.warning(
                    "%s failed after %d attempts: %s", description, max_retries, exc
                )
                raise
            delay = base_delay * (backoff_factor ** (attempt - 1))
            logger.info(
                "%s attempt %d/%d failed (%s), retrying in %.1fs...",
                description,
                attempt,
                max_retries,
                exc,
                delay,
            )
            time.sleep(delay)

    # Unreachable, but keeps type checkers happy
    raise RuntimeError("retry loop exited unexpectedly") from last_exc  # pragma: no cover
