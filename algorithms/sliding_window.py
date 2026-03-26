import time
from dataclasses import dataclass

from storage.base import StorageBackend


@dataclass
class SlidingWindowResult:
    """Result of a sliding window rate limit check."""

    allowed: bool
    remaining_requests: int
    retry_after: float | None  # seconds until the oldest request expires (None if allowed)


class SlidingWindow:
    """Sliding window log rate limiter.

    How it works:
    - Each request's timestamp is stored in a list (sorted set in Redis).
    - On consume(), timestamps older than `window_seconds` are pruned.
    - If the remaining count is under `max_requests`, the request is allowed
      and its timestamp is added.

    This fixes the fixed window boundary problem — the window slides with
    the current time, so there's no way to burst 2x at a window edge.

    Trade-off: stores one entry per request (vs one counter for fixed window),
    but Redis sorted sets with ZREMRANGEBYSCORE handle this efficiently.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        storage: StorageBackend,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.storage = storage

    def _prune(self, timestamps: list[float], now: float) -> list[float]:
        """Remove timestamps outside the current window."""
        cutoff = now - self.window_seconds
        return [ts for ts in timestamps if ts > cutoff]

    async def consume(self, key: str) -> SlidingWindowResult:
        """Try to record a request for the given key.

        Returns a SlidingWindowResult indicating whether the request is allowed,
        how many requests remain in the window, and when to retry if denied.
        """
        now = time.monotonic()
        state = await self.storage.get(key)

        timestamps: list[float] = state["timestamps"] if state else []

        # Prune expired entries
        timestamps = self._prune(timestamps, now)

        if len(timestamps) < self.max_requests:
            timestamps.append(now)
            await self.storage.set(key, {"timestamps": timestamps})
            remaining = self.max_requests - len(timestamps)
            return SlidingWindowResult(allowed=True, remaining_requests=remaining, retry_after=None)

        # Denied — oldest timestamp determines when a slot opens
        oldest = timestamps[0]
        retry_after = oldest + self.window_seconds - now
        await self.storage.set(key, {"timestamps": timestamps})
        return SlidingWindowResult(allowed=False, remaining_requests=0, retry_after=retry_after)
