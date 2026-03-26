import time
from dataclasses import dataclass

from storage.base import StorageBackend


@dataclass
class FixedWindowResult:
    """Result of a fixed window rate limit check."""

    allowed: bool
    remaining_requests: int
    retry_after: float | None  # seconds until the current window resets (None if allowed)


class FixedWindow:
    """Fixed window rate limiter.

    How it works:
    - Time is divided into fixed intervals of `window_seconds` each.
    - Each key gets a counter per window.
    - If the counter reaches `max_requests`, further requests are denied
      until the window resets.

    Trade-off vs token bucket: simpler to reason about ("100 requests per minute"),
    but susceptible to the boundary problem — a burst at the end of one window
    plus a burst at the start of the next can allow 2x max_requests in a short span.
    Sliding window (Step 4) fixes this.
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

    def _current_window(self, now: float) -> int:
        """Return the window number for the given timestamp.

        Integer division floors the timestamp into fixed-size buckets.
        Like DateTime.Ticks / ticksPerWindow in .NET.
        """
        return int(now // self.window_seconds)

    async def consume(self, key: str) -> FixedWindowResult:
        """Try to record a request for the given key.

        Returns a FixedWindowResult indicating whether the request is allowed,
        how many requests remain in the window, and when to retry if denied.
        """
        now = time.monotonic()
        current_window = self._current_window(now)

        storage_key = f"{key}:{current_window}"
        state = await self.storage.get(storage_key)

        if state is None:
            # First request in this window
            remaining = self.max_requests - 1
            await self.storage.set(storage_key, {"count": 1, "window": current_window})
            return FixedWindowResult(allowed=True, remaining_requests=remaining, retry_after=None)

        count = state["count"]

        if count < self.max_requests:
            count += 1
            remaining = self.max_requests - count
            await self.storage.set(storage_key, {"count": count, "window": current_window})
            return FixedWindowResult(allowed=True, remaining_requests=remaining, retry_after=None)

        # Denied — calculate time until next window
        window_start = current_window * self.window_seconds
        retry_after = window_start + self.window_seconds - now
        return FixedWindowResult(allowed=False, remaining_requests=0, retry_after=retry_after)
