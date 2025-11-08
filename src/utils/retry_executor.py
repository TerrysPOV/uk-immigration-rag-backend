"""
T044: RetryStrategyExecutor
Utility for executing retry strategies with configurable backoff

Retry Strategies (FR-WM-011):
1. immediate: 3 attempts, 0s delay
2. exponential: 5 attempts, 2x backoff with jitter (1s, 2s, 4s, 8s, 16s)
3. manual: No retry, pause workflow
4. circuit_breaker: Open after 5 failures, 60s cooldown

Usage Example:
    executor = RetryStrategyExecutor(strategy='exponential')
    result = await executor.execute(my_async_function, arg1, arg2)
"""

import asyncio
import time
import random
from typing import Callable, Any, Optional, Dict
from datetime import datetime, timedelta
from enum import Enum


class RetryStrategy(str, Enum):
    """Retry strategy types."""

    IMMEDIATE = "immediate"
    EXPONENTIAL = "exponential"
    MANUAL = "manual"
    CIRCUIT_BREAKER = "circuit_breaker"


class CircuitBreakerState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Circuit open (failing)
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """Circuit breaker implementation."""

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: int = 60):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            cooldown_seconds: Cooldown period in seconds
        """
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failure_count = 0
        self.state = CircuitBreakerState.CLOSED
        self.last_failure_time: Optional[datetime] = None

    def record_success(self):
        """Record successful execution."""
        if self.state == CircuitBreakerState.HALF_OPEN:
            print("[CircuitBreaker] Success in HALF_OPEN state - closing circuit")
            self.state = CircuitBreakerState.CLOSED

        self.failure_count = 0

    def record_failure(self):
        """Record failed execution."""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()

        if self.failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            print(
                f"[CircuitBreaker] Circuit OPEN after {self.failure_count} failures - cooldown {self.cooldown_seconds}s"
            )

    def can_execute(self) -> bool:
        """Check if execution is allowed."""
        if self.state == CircuitBreakerState.CLOSED:
            return True

        if self.state == CircuitBreakerState.OPEN:
            # Check if cooldown period has passed
            if self.last_failure_time:
                cooldown_elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
                if cooldown_elapsed >= self.cooldown_seconds:
                    print(
                        f"[CircuitBreaker] Cooldown period elapsed ({cooldown_elapsed:.2f}s) - entering HALF_OPEN"
                    )
                    self.state = CircuitBreakerState.HALF_OPEN
                    return True
                else:
                    print(
                        f"[CircuitBreaker] Circuit still OPEN ({cooldown_elapsed:.2f}s / {self.cooldown_seconds}s)"
                    )
                    return False

        if self.state == CircuitBreakerState.HALF_OPEN:
            return True

        return False


class RetryStrategyExecutor:
    """
    Execute functions with configurable retry strategies.

    Supports immediate, exponential, manual, and circuit breaker strategies.
    """

    def __init__(self, strategy: RetryStrategy, config: Optional[Dict[str, Any]] = None):
        """
        Initialize retry executor.

        Args:
            strategy: Retry strategy type
            config: Optional strategy-specific configuration

        Default Configurations:
            - immediate: {'max_attempts': 3, 'delay_ms': 0}
            - exponential: {'max_attempts': 5, 'initial_delay_ms': 1000, 'backoff_multiplier': 2.0, 'jitter_percentage': 0.2}
            - manual: {} (no retries)
            - circuit_breaker: {'failure_threshold': 5, 'cooldown_seconds': 60}
        """
        self.strategy = strategy
        self.config = config or self._default_config()
        self.circuit_breaker: Optional[CircuitBreaker] = None

        if strategy == RetryStrategy.CIRCUIT_BREAKER:
            self.circuit_breaker = CircuitBreaker(
                failure_threshold=self.config.get("failure_threshold", 5),
                cooldown_seconds=self.config.get("cooldown_seconds", 60),
            )

        print(f"[RetryStrategyExecutor] Initialized with strategy={strategy}, config={self.config}")

    def _default_config(self) -> Dict[str, Any]:
        """Get default configuration for strategy."""
        defaults = {
            RetryStrategy.IMMEDIATE: {"max_attempts": 3, "delay_ms": 0},
            RetryStrategy.EXPONENTIAL: {
                "max_attempts": 5,
                "initial_delay_ms": 1000,
                "backoff_multiplier": 2.0,
                "jitter_percentage": 0.2,
            },
            RetryStrategy.MANUAL: {},
            RetryStrategy.CIRCUIT_BREAKER: {"failure_threshold": 5, "cooldown_seconds": 60},
        }

        return defaults.get(self.strategy, {})

    async def execute(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with retry strategy.

        Args:
            func: Async function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            Exception: If all retry attempts fail

        Logs:
            - INFO: Retry attempt details
            - ERROR: Retry failures
        """
        if self.strategy == RetryStrategy.IMMEDIATE:
            return await self._execute_immediate(func, *args, **kwargs)

        elif self.strategy == RetryStrategy.EXPONENTIAL:
            return await self._execute_exponential(func, *args, **kwargs)

        elif self.strategy == RetryStrategy.MANUAL:
            return await self._execute_manual(func, *args, **kwargs)

        elif self.strategy == RetryStrategy.CIRCUIT_BREAKER:
            return await self._execute_circuit_breaker(func, *args, **kwargs)

        else:
            raise ValueError(f"Unknown retry strategy: {self.strategy}")

    async def _execute_immediate(self, func: Callable, *args, **kwargs) -> Any:
        """Execute with immediate retry (3 attempts, 0s delay)."""
        max_attempts = self.config.get("max_attempts", 3)
        last_exception = None

        for attempt in range(1, max_attempts + 1):
            try:
                print(f"[RetryStrategyExecutor] IMMEDIATE: Attempt {attempt}/{max_attempts}")
                result = await func(*args, **kwargs)
                print(f"[RetryStrategyExecutor] IMMEDIATE: Success on attempt {attempt}")
                return result

            except Exception as e:
                last_exception = e
                print(f"[RetryStrategyExecutor] IMMEDIATE: Attempt {attempt} failed - {str(e)}")

                if attempt < max_attempts:
                    # No delay for immediate retry
                    continue

        # All attempts failed
        print(f"[RetryStrategyExecutor] IMMEDIATE: All {max_attempts} attempts failed")
        raise last_exception

    async def _execute_exponential(self, func: Callable, *args, **kwargs) -> Any:
        """Execute with exponential backoff (5 attempts, 2x backoff with jitter)."""
        max_attempts = self.config.get("max_attempts", 5)
        initial_delay_ms = self.config.get("initial_delay_ms", 1000)
        backoff_multiplier = self.config.get("backoff_multiplier", 2.0)
        jitter_percentage = self.config.get("jitter_percentage", 0.2)

        last_exception = None
        delay_ms = initial_delay_ms

        for attempt in range(1, max_attempts + 1):
            try:
                print(f"[RetryStrategyExecutor] EXPONENTIAL: Attempt {attempt}/{max_attempts}")
                result = await func(*args, **kwargs)
                print(f"[RetryStrategyExecutor] EXPONENTIAL: Success on attempt {attempt}")
                return result

            except Exception as e:
                last_exception = e
                print(f"[RetryStrategyExecutor] EXPONENTIAL: Attempt {attempt} failed - {str(e)}")

                if attempt < max_attempts:
                    # Apply jitter: delay * (1 ± jitter_percentage)
                    jitter = delay_ms * jitter_percentage * (2 * random.random() - 1)
                    actual_delay_ms = delay_ms + jitter

                    print(
                        f"[RetryStrategyExecutor] EXPONENTIAL: Retrying in {actual_delay_ms:.0f}ms"
                    )
                    await asyncio.sleep(actual_delay_ms / 1000)

                    # Increase delay for next attempt
                    delay_ms *= backoff_multiplier

        # All attempts failed
        print(f"[RetryStrategyExecutor] EXPONENTIAL: All {max_attempts} attempts failed")
        raise last_exception

    async def _execute_manual(self, func: Callable, *args, **kwargs) -> Any:
        """Execute with manual retry (no automatic retry, pause workflow)."""
        try:
            print("[RetryStrategyExecutor] MANUAL: Executing (no retry)")
            result = await func(*args, **kwargs)
            print("[RetryStrategyExecutor] MANUAL: Success")
            return result

        except Exception as e:
            print(f"[RetryStrategyExecutor] MANUAL: Failed - {str(e)}")
            print("[RetryStrategyExecutor] MANUAL: No automatic retry - workflow will pause")
            raise

    async def _execute_circuit_breaker(self, func: Callable, *args, **kwargs) -> Any:
        """Execute with circuit breaker (open after 5 failures, 60s cooldown)."""
        if not self.circuit_breaker.can_execute():
            raise Exception(
                f"Circuit breaker is OPEN - service unavailable "
                f"(failures: {self.circuit_breaker.failure_count}, "
                f"cooldown: {self.circuit_breaker.cooldown_seconds}s)"
            )

        try:
            print(
                f"[RetryStrategyExecutor] CIRCUIT_BREAKER: Executing (state={self.circuit_breaker.state})"
            )
            result = await func(*args, **kwargs)
            print("[RetryStrategyExecutor] CIRCUIT_BREAKER: Success")
            self.circuit_breaker.record_success()
            return result

        except Exception as e:
            print(f"[RetryStrategyExecutor] CIRCUIT_BREAKER: Failed - {str(e)}")
            self.circuit_breaker.record_failure()
            raise
