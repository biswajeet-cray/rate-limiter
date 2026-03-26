import asyncio
import uuid

import pytest
import redis.asyncio as aioredis
import redis.exceptions

from storage.redis_backend import RedisBackend

# Unique prefix per test run so parallel runs don't collide
TEST_PREFIX = f"test:{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def backend():
    """Create a RedisBackend connected to local Redis, clean up after."""
    client = aioredis.Redis(host="localhost", port=6379, db=0)
    try:
        await client.ping()
    except (redis.exceptions.ConnectionError, ConnectionError, OSError):
        pytest.skip("Redis not running on localhost:6379")

    backend = RedisBackend(client)
    await backend.initialize()
    yield backend

    # Clean up test keys
    keys = await client.keys(f"{TEST_PREFIX}:*")
    if keys:
        await client.delete(*keys)
    await backend.close()


def _key(name: str) -> str:
    return f"{TEST_PREFIX}:{name}"


# --- Basic get/set interface ---


async def test_get_nonexistent(backend: RedisBackend):
    result = await backend.get(_key("missing"))
    assert result is None


async def test_set_and_get(backend: RedisBackend):
    await backend.set(_key("basic"), {"count": 5, "name": "test"})
    result = await backend.get(_key("basic"))
    assert result is not None
    assert result["count"] == 5
    assert result["name"] == "test"


async def test_set_overwrites(backend: RedisBackend):
    key = _key("overwrite")
    await backend.set(key, {"val": 1})
    await backend.set(key, {"val": 2})
    result = await backend.get(key)
    assert result["val"] == 2


# --- Token bucket Lua script ---


async def test_token_bucket_first_request_allowed(backend: RedisBackend):
    result = await backend.atomic_token_bucket(_key("tb1"), max_tokens=5, refill_rate=1.0)
    assert result["allowed"] is True
    assert result["remaining"] == 4
    assert result["retry_after"] is None


async def test_token_bucket_exhaustion(backend: RedisBackend):
    key = _key("tb_exhaust")
    for _ in range(5):
        result = await backend.atomic_token_bucket(key, max_tokens=5, refill_rate=1.0)
        assert result["allowed"] is True

    result = await backend.atomic_token_bucket(key, max_tokens=5, refill_rate=1.0)
    assert result["allowed"] is False
    assert result["retry_after"] is not None
    assert result["retry_after"] > 0


async def test_token_bucket_refill(backend: RedisBackend):
    key = _key("tb_refill")
    # Exhaust tokens
    for _ in range(2):
        await backend.atomic_token_bucket(key, max_tokens=2, refill_rate=100.0)

    result = await backend.atomic_token_bucket(key, max_tokens=2, refill_rate=100.0)
    assert result["allowed"] is False

    # High refill rate means tokens recover quickly — wait a tiny bit
    await asyncio.sleep(0.05)
    result = await backend.atomic_token_bucket(key, max_tokens=2, refill_rate=100.0)
    assert result["allowed"] is True


async def test_token_bucket_independent_keys(backend: RedisBackend):
    key1, key2 = _key("tb_k1"), _key("tb_k2")
    await backend.atomic_token_bucket(key1, max_tokens=1, refill_rate=1.0)

    result = await backend.atomic_token_bucket(key1, max_tokens=1, refill_rate=1.0)
    assert result["allowed"] is False

    result = await backend.atomic_token_bucket(key2, max_tokens=1, refill_rate=1.0)
    assert result["allowed"] is True


# --- Fixed window Lua script ---


async def test_fixed_window_first_request_allowed(backend: RedisBackend):
    result = await backend.atomic_fixed_window(_key("fw1"), max_requests=5, window_seconds=60)
    assert result["allowed"] is True
    assert result["remaining"] == 4
    assert result["retry_after"] is None


async def test_fixed_window_exhaustion(backend: RedisBackend):
    key = _key("fw_exhaust")
    for _ in range(3):
        result = await backend.atomic_fixed_window(key, max_requests=3, window_seconds=60)
        assert result["allowed"] is True

    result = await backend.atomic_fixed_window(key, max_requests=3, window_seconds=60)
    assert result["allowed"] is False
    assert result["remaining"] == 0
    assert result["retry_after"] is not None
    assert result["retry_after"] > 0


async def test_fixed_window_independent_keys(backend: RedisBackend):
    key1, key2 = _key("fw_k1"), _key("fw_k2")
    await backend.atomic_fixed_window(key1, max_requests=1, window_seconds=60)

    result = await backend.atomic_fixed_window(key1, max_requests=1, window_seconds=60)
    assert result["allowed"] is False

    result = await backend.atomic_fixed_window(key2, max_requests=1, window_seconds=60)
    assert result["allowed"] is True


# --- Sliding window Lua script ---


async def test_sliding_window_first_request_allowed(backend: RedisBackend):
    result = await backend.atomic_sliding_window(_key("sw1"), max_requests=5, window_seconds=60)
    assert result["allowed"] is True
    assert result["remaining"] == 4
    assert result["retry_after"] is None


async def test_sliding_window_exhaustion(backend: RedisBackend):
    key = _key("sw_exhaust")
    for _ in range(3):
        result = await backend.atomic_sliding_window(key, max_requests=3, window_seconds=60)
        assert result["allowed"] is True

    result = await backend.atomic_sliding_window(key, max_requests=3, window_seconds=60)
    assert result["allowed"] is False
    assert result["remaining"] == 0
    assert result["retry_after"] is not None
    assert result["retry_after"] > 0


async def test_sliding_window_expiry(backend: RedisBackend):
    """Entries expire after window_seconds, freeing up capacity."""
    key = _key("sw_expiry")

    # Use a 1-second window so we can test expiry quickly
    await backend.atomic_sliding_window(key, max_requests=1, window_seconds=1)
    result = await backend.atomic_sliding_window(key, max_requests=1, window_seconds=1)
    assert result["allowed"] is False

    # Wait for the window to pass
    await asyncio.sleep(1.1)
    result = await backend.atomic_sliding_window(key, max_requests=1, window_seconds=1)
    assert result["allowed"] is True


async def test_sliding_window_independent_keys(backend: RedisBackend):
    key1, key2 = _key("sw_k1"), _key("sw_k2")
    await backend.atomic_sliding_window(key1, max_requests=1, window_seconds=60)

    result = await backend.atomic_sliding_window(key1, max_requests=1, window_seconds=60)
    assert result["allowed"] is False

    result = await backend.atomic_sliding_window(key2, max_requests=1, window_seconds=60)
    assert result["allowed"] is True


# --- Cross-algorithm: all three work through the same backend ---


async def test_all_algorithms_coexist(backend: RedisBackend):
    """Different algorithm keys don't interfere with each other."""
    tb_key = _key("coexist_tb")
    fw_key = _key("coexist_fw")
    sw_key = _key("coexist_sw")

    r1 = await backend.atomic_token_bucket(tb_key, max_tokens=1, refill_rate=1.0)
    r2 = await backend.atomic_fixed_window(fw_key, max_requests=1, window_seconds=60)
    r3 = await backend.atomic_sliding_window(sw_key, max_requests=1, window_seconds=60)

    assert r1["allowed"] is True
    assert r2["allowed"] is True
    assert r3["allowed"] is True

    # All exhausted
    r1 = await backend.atomic_token_bucket(tb_key, max_tokens=1, refill_rate=1.0)
    r2 = await backend.atomic_fixed_window(fw_key, max_requests=1, window_seconds=60)
    r3 = await backend.atomic_sliding_window(sw_key, max_requests=1, window_seconds=60)

    assert r1["allowed"] is False
    assert r2["allowed"] is False
    assert r3["allowed"] is False
