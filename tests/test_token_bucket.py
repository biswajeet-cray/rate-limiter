from unittest.mock import patch

from algorithms.token_bucket import ConsumeResult, TokenBucket
from storage.memory_backend import MemoryBackend


def make_bucket(max_tokens: int = 5, refill_rate: float = 1.0) -> TokenBucket:
    return TokenBucket(max_tokens=max_tokens, refill_rate=refill_rate, storage=MemoryBackend())


# --- Basic allow / deny ---


async def test_first_request_allowed():
    bucket = make_bucket(max_tokens=5)
    result = await bucket.consume("user1")
    assert result.allowed is True
    assert result.remaining_tokens == 4
    assert result.retry_after is None


async def test_requests_allowed_until_exhausted():
    bucket = make_bucket(max_tokens=3)
    for _ in range(3):
        result = await bucket.consume("user1")
        assert result.allowed is True

    result = await bucket.consume("user1")
    assert result.allowed is False
    assert result.remaining_tokens < 1
    assert result.retry_after is not None
    assert result.retry_after > 0


async def test_denied_result_has_retry_after():
    bucket = make_bucket(max_tokens=1, refill_rate=2.0)
    await bucket.consume("user1")  # takes the only token

    result = await bucket.consume("user1")
    assert result.allowed is False
    assert result.retry_after is not None
    # At 2 tokens/sec, retry_after should be ~0.5s
    assert result.retry_after <= 0.5 + 0.1


# --- Refill after time passes ---


async def test_tokens_refill_over_time():
    bucket = make_bucket(max_tokens=2, refill_rate=1.0)

    # Exhaust all tokens
    await bucket.consume("user1")
    await bucket.consume("user1")
    result = await bucket.consume("user1")
    assert result.allowed is False

    # Simulate 1 second passing — should refill 1 token
    with patch("algorithms.token_bucket.time") as mock_time:
        # The last call set last_refill to some monotonic value.
        # We need the next call to see 1 second later.
        stored = await bucket.storage.get("user1")
        mock_time.monotonic.return_value = stored["last_refill"] + 1.0

        result = await bucket.consume("user1")
        assert result.allowed is True


async def test_refill_does_not_exceed_max_tokens():
    bucket = make_bucket(max_tokens=3, refill_rate=10.0)

    await bucket.consume("user1")  # 2 remaining

    # Simulate 10 seconds passing — 10*10=100 tokens refilled, but capped at max_tokens
    with patch("algorithms.token_bucket.time") as mock_time:
        stored = await bucket.storage.get("user1")
        mock_time.monotonic.return_value = stored["last_refill"] + 10.0

        result = await bucket.consume("user1")
        assert result.allowed is True
        assert result.remaining_tokens == 2  # 3 (capped) - 1 consumed


async def test_partial_refill():
    bucket = make_bucket(max_tokens=5, refill_rate=2.0)

    # Use all 5 tokens
    for _ in range(5):
        await bucket.consume("user1")

    # Simulate 0.5 seconds — should refill 1 token (0.5 * 2.0)
    with patch("algorithms.token_bucket.time") as mock_time:
        stored = await bucket.storage.get("user1")
        mock_time.monotonic.return_value = stored["last_refill"] + 0.5

        result = await bucket.consume("user1")
        assert result.allowed is True
        assert result.remaining_tokens < 1  # had ~1, consumed 1 => ~0


# --- Burst capacity ---


async def test_burst_capacity():
    """A full bucket allows max_tokens requests instantly (burst)."""
    bucket = make_bucket(max_tokens=10, refill_rate=1.0)

    results = []
    for _ in range(10):
        results.append(await bucket.consume("user1"))

    assert all(r.allowed for r in results)

    # 11th request should be denied
    result = await bucket.consume("user1")
    assert result.allowed is False


# --- Concurrent keys ---


async def test_independent_keys():
    """Different keys have independent buckets."""
    bucket = make_bucket(max_tokens=2)

    # Exhaust user1
    await bucket.consume("user1")
    await bucket.consume("user1")
    result = await bucket.consume("user1")
    assert result.allowed is False

    # user2 should still have a full bucket
    result = await bucket.consume("user2")
    assert result.allowed is True
    assert result.remaining_tokens == 1


async def test_many_keys_independent():
    """Multiple keys don't interfere with each other."""
    bucket = make_bucket(max_tokens=3)

    for key in ["api_key_1", "api_key_2", "api_key_3"]:
        result = await bucket.consume(key)
        assert result.allowed is True
        assert result.remaining_tokens == 2

    # Exhaust api_key_1
    await bucket.consume("api_key_1")
    await bucket.consume("api_key_1")
    result = await bucket.consume("api_key_1")
    assert result.allowed is False

    # Others still have tokens
    result = await bucket.consume("api_key_2")
    assert result.allowed is True


# --- Edge cases ---


async def test_consume_result_dataclass():
    result = ConsumeResult(allowed=True, remaining_tokens=4.0, retry_after=None)
    assert result.allowed is True
    assert result.remaining_tokens == 4.0
    assert result.retry_after is None


async def test_single_token_bucket():
    """Bucket with max_tokens=1 allows exactly 1 request."""
    bucket = make_bucket(max_tokens=1, refill_rate=0.5)

    result = await bucket.consume("user1")
    assert result.allowed is True
    assert result.remaining_tokens == 0

    result = await bucket.consume("user1")
    assert result.allowed is False
