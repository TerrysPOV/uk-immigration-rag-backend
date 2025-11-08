"""
Rate Limiting Middleware for Ingestion Endpoints

Feature 011: Security Enhancement (T073)
Implements rate limiting to prevent abuse of ingestion endpoints.

Rate Limits:
- POST /api/v1/ingestion/url: 10 requests per minute per user
- POST /api/v1/ingestion/upload: 10 requests per minute per user
- POST /api/v1/ingestion/cloud: 10 requests per minute per user
- WebSocket connections: 5 concurrent connections per user

Implementation uses Redis (already available for Celery) for distributed rate limiting.
"""

import time
from typing import Dict, Optional
from functools import wraps
from fastapi import HTTPException, Request, status
import redis
import os

# Redis client for rate limiting (shared with Celery)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/1")  # Use DB 1 for rate limiting


class RateLimiter:
    """
    Token bucket rate limiter using Redis.

    Features:
    - Distributed rate limiting (works across multiple API instances)
    - Per-user rate limits
    - Configurable rate and burst limits
    - Automatic token replenishment
    """

    def __init__(self, redis_url: str = REDIS_URL):
        """Initialize Redis connection for rate limiting"""
        try:
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            self.redis_client.ping()  # Test connection
        except (redis.ConnectionError, redis.TimeoutError):
            # Fallback to in-memory rate limiting if Redis unavailable
            self.redis_client = None
            self._in_memory_buckets: Dict[str, Dict] = {}

    def check_rate_limit(
        self,
        key: str,
        max_requests: int = 10,
        window_seconds: int = 60
    ) -> tuple[bool, int]:
        """
        Check if request is within rate limit.

        Args:
            key: Unique identifier (e.g., user_id:endpoint)
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds

        Returns:
            Tuple of (allowed: bool, retry_after_seconds: int)
        """
        if self.redis_client:
            return self._check_redis_rate_limit(key, max_requests, window_seconds)
        else:
            return self._check_memory_rate_limit(key, max_requests, window_seconds)

    def _check_redis_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int
    ) -> tuple[bool, int]:
        """Redis-based distributed rate limiting"""
        redis_key = f"rate_limit:{key}"
        current_time = int(time.time())
        window_start = current_time - window_seconds

        try:
            # Use Redis sorted set for sliding window rate limiting
            # Score = timestamp, Member = request_id

            # Remove expired entries
            self.redis_client.zremrangebyscore(redis_key, 0, window_start)

            # Count requests in current window
            request_count = self.redis_client.zcard(redis_key)

            if request_count >= max_requests:
                # Get oldest request timestamp to calculate retry_after
                oldest_request = self.redis_client.zrange(redis_key, 0, 0, withscores=True)
                if oldest_request:
                    oldest_timestamp = int(oldest_request[0][1])
                    retry_after = window_seconds - (current_time - oldest_timestamp)
                    return False, max(1, retry_after)
                return False, window_seconds

            # Add new request
            request_id = f"{current_time}:{request_count}"
            self.redis_client.zadd(redis_key, {request_id: current_time})

            # Set expiry on key (cleanup)
            self.redis_client.expire(redis_key, window_seconds * 2)

            return True, 0

        except Exception as e:
            # If Redis fails, allow request but log error
            print(f"Rate limiter Redis error: {e}")
            return True, 0

    def _check_memory_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int
    ) -> tuple[bool, int]:
        """Fallback in-memory rate limiting (single instance only)"""
        current_time = time.time()

        if key not in self._in_memory_buckets:
            self._in_memory_buckets[key] = {
                'requests': [],
                'window_seconds': window_seconds
            }

        bucket = self._in_memory_buckets[key]
        window_start = current_time - window_seconds

        # Remove expired requests
        bucket['requests'] = [
            req_time for req_time in bucket['requests']
            if req_time > window_start
        ]

        if len(bucket['requests']) >= max_requests:
            # Calculate retry_after
            oldest_request = min(bucket['requests'])
            retry_after = int(window_seconds - (current_time - oldest_request))
            return False, max(1, retry_after)

        # Add new request
        bucket['requests'].append(current_time)
        return True, 0


# Global rate limiter instance
rate_limiter = RateLimiter()


def rate_limit(
    max_requests: int = 10,
    window_seconds: int = 60,
    key_prefix: str = "api"
):
    """
    Decorator for rate limiting FastAPI endpoints.

    Usage:
        @router.post("/api/v1/ingestion/url")
        @rate_limit(max_requests=10, window_seconds=60, key_prefix="ingestion_url")
        async def ingest_urls(...):
            ...

    Args:
        max_requests: Maximum requests allowed in window (default: 10)
        window_seconds: Time window in seconds (default: 60)
        key_prefix: Prefix for rate limit key (default: "api")
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract request and user from kwargs
            request: Optional[Request] = kwargs.get('request')
            user: Optional[dict] = kwargs.get('user')

            if not user:
                # If no user in kwargs, check function parameters
                for arg in args:
                    if isinstance(arg, dict) and 'user_id' in arg:
                        user = arg
                        break

            # Build rate limit key: user_id:endpoint
            user_id = user.get('user_id', 'anonymous') if user else 'anonymous'
            rate_limit_key = f"{user_id}:{key_prefix}"

            # Check rate limit
            allowed, retry_after = rate_limiter.check_rate_limit(
                rate_limit_key,
                max_requests=max_requests,
                window_seconds=window_seconds
            )

            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Maximum {max_requests} requests per {window_seconds} seconds allowed.",
                    headers={"Retry-After": str(retry_after)}
                )

            # Execute endpoint
            return await func(*args, **kwargs)

        return wrapper
    return decorator


def check_websocket_connection_limit(user_id: str, max_connections: int = 5) -> bool:
    """
    Check if user has exceeded concurrent WebSocket connection limit.

    Args:
        user_id: User identifier
        max_connections: Maximum concurrent connections (default: 5)

    Returns:
        True if connection allowed, False if limit exceeded

    Usage:
        if not check_websocket_connection_limit(user_id, max_connections=5):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    """
    rate_limit_key = f"{user_id}:websocket_connections"
    allowed, _ = rate_limiter.check_rate_limit(
        rate_limit_key,
        max_requests=max_connections,
        window_seconds=3600  # 1 hour window (connections are long-lived)
    )
    return allowed


def release_websocket_connection(user_id: str):
    """
    Release a WebSocket connection slot when connection closes.

    Args:
        user_id: User identifier

    Usage:
        try:
            # WebSocket connection code
            ...
        finally:
            release_websocket_connection(user_id)
    """
    rate_limit_key = f"rate_limit:{user_id}:websocket_connections"

    if rate_limiter.redis_client:
        try:
            # Remove one entry from sorted set
            rate_limiter.redis_client.zpopmin(rate_limit_key, count=1)
        except Exception as e:
            print(f"Error releasing WebSocket connection: {e}")
