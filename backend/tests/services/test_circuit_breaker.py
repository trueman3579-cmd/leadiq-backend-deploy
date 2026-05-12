"""Tests for circuit breaker state machine — CLOSED, OPEN, and failure counting."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from backend.llm.circuit_breaker import (
    CircuitState,
    get_state,
    record_failure,
    record_success,
)


class TestCircuitBreaker:
    """Verify circuit breaker state transitions."""

    def test_initial_closed_state(self) -> None:
        """When no data is in Redis, the breaker should be CLOSED."""
        state = get_state("test_circuit")
        assert state == CircuitState.CLOSED, (
            "Circuit should start CLOSED when no Redis data exists"
        )

    @patch("backend.llm.circuit_breaker._r")
    def test_record_success_resets(self, mock_r: MagicMock) -> None:
        """Calling record_success should reset failures to 0 and set state to closed."""
        mock_r.hget.return_value = 3
        record_success("test_circuit")
        mock_r.hset.assert_called_once_with(
            "gemini:circuit:test_circuit",
            mapping={"state": "closed", "failures": 0},
        )

    @patch("backend.llm.circuit_breaker._r")
    def test_record_failure_increments(self, mock_r: MagicMock) -> None:
        """Calling record_failure should increment the failure counter."""
        mock_r.hget.return_value = 0
        record_failure("test_circuit", threshold=5)
        mock_r.hset.assert_called()
        # Verify failures were incremented
        call_kwargs = mock_r.hset.call_args[1]
        assert call_kwargs["mapping"]["failures"] == 1

    @patch("backend.llm.circuit_breaker._r")
    def test_record_failure_opens_at_threshold(self, mock_r: MagicMock) -> None:
        """When failures reach threshold, the circuit should OPEN."""
        # Simulate current failures = 4, so next increment hits threshold=5
        mock_r.hget.return_value = 4

        with patch.object(time, "time", return_value=1000.0):
            record_failure("test_circuit", threshold=5, recovery_timeout=60)

        # hset should be called at least once with state="open"
        open_call = None
        for call in mock_r.hset.call_args_list:
            mapping = call[1].get("mapping", {})
            if mapping.get("state") == "open":
                open_call = call
                break

        assert open_call is not None, (
            "Circuit should transition to OPEN when failures >= threshold"
        )
        # Verify last_failure is recorded
        assert open_call[1]["mapping"]["last_failure"] == 1000.0

    @patch("backend.llm.circuit_breaker._r")
    def test_get_state_returns_closed_when_no_redis(
        self, mock_r: MagicMock
    ) -> None:
        """get_state should return CLOSED when Redis is not available."""
        # Simulate _r being None (Redis unavailable)
        with patch("backend.llm.circuit_breaker._r", None):
            state = get_state("test_circuit")
            assert state == CircuitState.CLOSED

    @patch("backend.llm.circuit_breaker._r", None)
    def test_record_failure_no_redis(self) -> None:
        """record_failure should not raise when Redis is unavailable."""
        # Should not raise any exception
        record_failure("no_redis_test", threshold=5)

    @patch("backend.llm.circuit_breaker._r", None)
    def test_record_success_no_redis(self) -> None:
        """record_success should not raise when Redis is unavailable."""
        record_success("no_redis_test")
