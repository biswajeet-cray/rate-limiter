import time
from dataclasses import dataclass

from storage.base import StorageBackend


@dataclass
class ConsumeResult:
    """Result of a token bucket consume operation."""

    allowed: bool
    remaining_tokens: float
    retry_after: float | None  # seconds until a token is available (None if allowed)


class TokenBucket:
    """Token bucket rate limiter.

    How it works:
    - Each key gets a bucket that holds up to `max_tokens` tokens.
    - Tokens refill at `refill_rate` tokens per second.
    - Each consume() call tries to take 1 token.
    - If tokens are available -> allowed. If empty -> denied.

    The burst capacity equals max_tokens — a full bucket allows that many
    requests instantly before the steady-state rate (refill_rate/sec) kicks in.
    """

    def __init__(
        self,
        max_tokens: int,
        refill_rate: float,
        storage: StorageBackend,
    ) -> None:
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self.storage = storage

    def _refill(self, tokens: float, last_refill: float, now: float) -> float:
        """Calculate token count after refill based on elapsed time."""
        elapsed = now - last_refill
        new_tokens = tokens + elapsed * self.refill_rate
        return min(new_tokens, self.max_tokens)

    async def consume(self, key: str) -> ConsumeResult:
        """Try to consume 1 token for the given key.

        Returns a ConsumeResult indicating whether the request is allowed,
        how many tokens remain, and when to retry if denied.
        """
        now = time.monotonic()
        bucket = await self.storage.get(key)

        if bucket is None:
            # First request for this key — start with a full bucket minus 1
            tokens = self.max_tokens - 1
            await self.storage.set(key, {"tokens": tokens, "last_refill": now})
            return ConsumeResult(allowed=True, remaining_tokens=tokens, retry_after=None)

        # Refill tokens based on time elapsed
        tokens = self._refill(bucket["tokens"], bucket["last_refill"], now)

        if tokens >= 1:
            tokens -= 1
            await self.storage.set(key, {"tokens": tokens, "last_refill": now})
            return ConsumeResult(allowed=True, remaining_tokens=tokens, retry_after=None)

        # Denied — calculate how long until 1 token is available
        deficit = 1 - tokens
        retry_after = deficit / self.refill_rate
        await self.storage.set(key, {"tokens": tokens, "last_refill": now})
        return ConsumeResult(allowed=False, remaining_tokens=tokens, retry_after=retry_after)
