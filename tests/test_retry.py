"""Tests for the retry utility."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from flight_monitor.retry import retry_on_exception


class TestRetryOnException:
    def test_succeeds_first_try(self):
        result = retry_on_exception(lambda: 42, description="test")
        assert result == 42

    def test_retries_on_failure_then_succeeds(self):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "ok"

        with patch("flight_monitor.retry.time.sleep"):
            result = retry_on_exception(
                flaky,
                max_retries=3,
                retryable=(ConnectionError,),
                description="flaky op",
            )
        assert result == "ok"
        assert call_count == 3

    def test_raises_after_max_retries(self):
        def always_fail():
            raise ConnectionError("permanent")

        with (
            patch("flight_monitor.retry.time.sleep"),
            pytest.raises(ConnectionError, match="permanent"),
        ):
            retry_on_exception(
                always_fail,
                max_retries=3,
                retryable=(ConnectionError,),
                description="failing op",
            )

    def test_non_retryable_exception_raised_immediately(self):
        call_count = 0

        def bad():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError, match="not retryable"):
            retry_on_exception(
                bad,
                max_retries=3,
                retryable=(ConnectionError,),
                description="bad op",
            )
        assert call_count == 1

    def test_exponential_backoff_delays(self):
        call_count = 0

        def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise OSError("fail")
            return "done"

        with patch("flight_monitor.retry.time.sleep") as mock_sleep:
            retry_on_exception(
                fail_twice,
                max_retries=3,
                base_delay=1.0,
                backoff_factor=2.0,
                retryable=(OSError,),
                description="backoff test",
            )
        # First retry: 1.0 * 2^0 = 1.0, Second retry: 1.0 * 2^1 = 2.0
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)
