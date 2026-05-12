"""
backend/services/circuit_breaker.py -- Circuit Breaker Pattern for External Service Calls

Implements the circuit breaker pattern to prevent cascading failures when external
services (Gemini API, GitHub API, etc.) become unavailable. Three states:

    CLOSED   — Normal operation. Calls pass through.
    OPEN     — Failure threshold reached. Calls are rejected immediately.
    HALF_OPEN — Testing recovery. Limited calls allowed; success resets to CLOSED.

Usage:
    from backend.services.circuit_breaker import CircuitBreaker, CircuitBreakerOpen

    cb = CircuitBreaker(name="gemini", failure_threshold=5, recovery_timeout=60)

    async def call_gemini() -> dict:
        return await cb.call(gemini_api_func, prompt=prompt)

    # Or use as a decorator:
    @cb
    async def call_gemini(prompt: str) -> dict: ...
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, ParamSpec, TypeVar

import structlog

logger = structlog.get_logger()

P = ParamSpec("P")
R = TypeVar("R")


class CircuitBreakerState(Enum):
    """Possible states for a circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    """Raised when a call is rejected because the circuit breaker is OPEN."""

    def __init__(self, name: str, state: CircuitBreakerState) -> None:
        self.circuit_name = name
        self.circuit_state = state
        super().__init__(f"Circuit '{name}' is {state.value} — call rejected")


class CircuitBreaker:
    """Circuit breaker for protecting external service calls.

    Prevents repeated calls to an unresponsive service, allowing it time to
    recover. After the recovery timeout, a limited number of test calls are
    allowed (HALF_OPEN). If they succeed, the circuit resets to CLOSED.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout_seconds: int = 60,
        half_open_max_requests: int = 3,
    ) -> None:
        """Initialise the circuit breaker.

        Args:
            name: Identifier for this circuit (e.g. "gemini", "github_api").
            failure_threshold: Consecutive failures before opening the circuit.
            recovery_timeout_seconds: Seconds to wait before attempting recovery.
            half_open_max_requests: Successful requests needed in HALF_OPEN to
                                    reset to CLOSED.
        """
        self.name: str = name
        self.failure_threshold: int = failure_threshold
        self.recovery_timeout_seconds: int = recovery_timeout_seconds
        self.half_open_max_requests: int = half_open_max_requests

        # Internal state
        self._state: CircuitBreakerState = CircuitBreakerState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._last_failure_time: datetime | None = None
        self._half_open_calls: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()

    # ── Properties ─────────────────────────────────────────────────────────────────

    @property
    def state(self) -> CircuitBreakerState:
        """Current state of the circuit breaker."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Current consecutive failure count."""
        return self._failure_count

    @property
    def is_open(self) -> bool:
        """True if the circuit is currently OPEN."""
        return self._state is CircuitBreakerState.OPEN

    # ── Core Call Method ───────────────────────────────────────────────────────────

    async def call(
        self,
        func: Callable[P, Coroutine[Any, Any, R]],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        """Execute a function with circuit breaker protection.

        Args:
            func: Async function to call.
            *args: Positional arguments forwarded to func.
            **kwargs: Keyword arguments forwarded to func.

        Returns:
            The return value of the wrapped function.

        Raises:
            CircuitBreakerOpenError: If the circuit is OPEN and recovery timeout
                                     has not elapsed.
            Exception: Any exception raised by the wrapped function.
        """
        async with self._lock:
            await self._check_state()

            if self._state is CircuitBreakerState.OPEN:
                raise CircuitBreakerOpenError(self.name, self._state)

            if self._state is CircuitBreakerState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_requests:
                    raise CircuitBreakerOpenError(self.name, self._state)
                self._half_open_calls += 1

            half_open_call_count = self._half_open_calls

        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                self._on_success()
            return result
        except Exception as exc:
            async with self._lock:
                self._on_failure(exc)
            raise

    # ── Decorator Support ──────────────────────────────────────────────────────────

    async def __call__(
        self,
        func: Callable[P, Coroutine[Any, Any, R]],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        """Allow the circuit breaker instance to be used as a decorator."""
        return await self.call(func, *args, **kwargs)

    # ── State Transitions ─────────────────────────────────────────────────────────

    async def _check_state(self) -> None:
        """Evaluate and transition state before a call is made.

        If OPEN and the recovery timeout has elapsed, transition to HALF_OPEN.
        """
        if self._state is not CircuitBreakerState.OPEN:
            return

        if self._should_attempt_reset():
            logger.info(
                "circuit_breaker_half_open",
                name=self.name,
                recovery_timeout=self.recovery_timeout_seconds,
            )
            self._state = CircuitBreakerState.HALF_OPEN
            self._half_open_calls = 0
            self._success_count = 0

    def _on_success(self) -> None:
        """Handle a successful call and update state accordingly.

        In HALF_OPEN: increment success count; if threshold reached, reset to CLOSED.
        In CLOSED: reset failure count to zero.
        """
        if self._state is CircuitBreakerState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.half_open_max_requests:
                self._reset()
                logger.info(
                    "circuit_breaker_recovered",
                    name=self.name,
                )
        else:
            self._failure_count = 0

    def _on_failure(self, exception: Exception) -> None:
        """Handle a failed call and update state accordingly.

        Increments the failure counter. If the threshold is reached, transition
        to OPEN and log the event.

        Args:
            exception: The exception that caused the failure.
        """
        self._failure_count += 1
        self._last_failure_time = datetime.now(timezone.utc)

        if self._failure_count >= self.failure_threshold:
            self._state = CircuitBreakerState.OPEN
            logger.error(
                "circuit_breaker_opened",
                name=self.name,
                failures=self._failure_count,
                threshold=self.failure_threshold,
                error=str(exception),
            )

    def _should_attempt_reset(self) -> bool:
        """Determine whether enough time has passed to attempt a reset.

        Returns:
            True if the recovery timeout has elapsed since the last failure.
        """
        if self._last_failure_time is None:
            return True
        elapsed = datetime.now(timezone.utc) - self._last_failure_time
        return elapsed >= timedelta(seconds=self.recovery_timeout_seconds)

    def _reset(self) -> None:
        """Reset the circuit breaker to its initial CLOSED state.

        Clears all failure/success counters and the last failure timestamp.
        """
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time = None

    # ── Manual Control ─────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED state.

        Useful for administrative intervention or after a known service recovery.
        """
        self._reset()
        logger.info("circuit_breaker_manually_reset", name=self.name)
