import json
import time
import uuid
from typing import Any

import redis.asyncio as redis

from storage.base import StorageBackend

# --- Lua scripts ---
# These run atomically on the Redis server (like SQL stored procedures).
# No race conditions: Redis is single-threaded and executes each script
# without interruption, even with multiple API processes.

# Token bucket: atomic refill + consume
# KEYS[1] = rate limit key
# ARGV = [max_tokens, refill_rate, now]
# Returns: [allowed(0/1), remaining_tokens, retry_after(-1 if allowed)]
TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local max_tokens = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil then
    tokens = max_tokens - 1
    redis.call('HMSET', key, 'tokens', tostring(tokens), 'last_refill', tostring(now))
    return {1, tostring(tokens), "-1"}
end

local elapsed = now - last_refill
local new_tokens = math.min(tokens + elapsed * refill_rate, max_tokens)

if new_tokens >= 1 then
    new_tokens = new_tokens - 1
    redis.call('HMSET', key, 'tokens', tostring(new_tokens), 'last_refill', tostring(now))
    return {1, tostring(new_tokens), "-1"}
end

local deficit = 1 - new_tokens
local retry_after = deficit / refill_rate
redis.call('HMSET', key, 'tokens', tostring(new_tokens), 'last_refill', tostring(now))
return {0, tostring(new_tokens), tostring(retry_after)}
"""

# Fixed window: atomic increment + check + TTL
# KEYS[1] = rate limit key (includes window number)
# ARGV = [max_requests, window_seconds]
# Returns: [allowed(0/1), remaining, retry_after(-1 if allowed)]
FIXED_WINDOW_SCRIPT = """
local key = KEYS[1]
local max_requests = tonumber(ARGV[1])
local window_seconds = tonumber(ARGV[2])

local count = redis.call('INCR', key)
if count == 1 then
    redis.call('EXPIRE', key, window_seconds)
end

if count <= max_requests then
    return {1, max_requests - count, "-1"}
end

local ttl = redis.call('TTL', key)
return {0, 0, tostring(ttl)}
"""

# Sliding window: atomic ZREMRANGEBYSCORE + ZCARD + ZADD
# KEYS[1] = rate limit key (sorted set)
# ARGV = [max_requests, window_seconds, now, unique_member_id]
# Returns: [allowed(0/1), remaining, retry_after(-1 if allowed)]
SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local max_requests = tonumber(ARGV[1])
local window_seconds = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local member = ARGV[4]

local cutoff = now - window_seconds
redis.call('ZREMRANGEBYSCORE', key, '-inf', tostring(cutoff))

local count = redis.call('ZCARD', key)

if count < max_requests then
    redis.call('ZADD', key, tostring(now), member)
    redis.call('EXPIRE', key, window_seconds)
    return {1, max_requests - count - 1, "-1"}
end

local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local retry_after = "-1"
if oldest and #oldest >= 2 then
    retry_after = tostring(tonumber(oldest[2]) + window_seconds - now)
end

return {0, 0, retry_after}
"""


class RedisBackend(StorageBackend):
    """Redis storage backend with atomic Lua script operations.

    Implements the basic get/set interface for compatibility, plus atomic
    consume methods for each algorithm. The atomic methods are what you'd
    use in production — they eliminate race conditions that exist with
    separate get/set calls across multiple API processes.

    Think of it like the difference between:
    - SELECT then UPDATE (race condition) vs
    - A single stored procedure (atomic)
    """

    def __init__(self, client: redis.Redis) -> None:
        self._client = client
        self._token_bucket_sha: str | None = None
        self._fixed_window_sha: str | None = None
        self._sliding_window_sha: str | None = None

    async def initialize(self) -> None:
        """Pre-load Lua scripts into Redis (returns SHA hashes for EVALSHA).

        Like compiling stored procedures — do it once at startup,
        then call by SHA for efficiency.
        """
        self._token_bucket_sha = await self._client.script_load(TOKEN_BUCKET_SCRIPT)
        self._fixed_window_sha = await self._client.script_load(FIXED_WINDOW_SCRIPT)
        self._sliding_window_sha = await self._client.script_load(SLIDING_WINDOW_SCRIPT)

    # --- Basic StorageBackend interface (for compatibility) ---

    async def get(self, key: str) -> dict[str, Any] | None:
        data = await self._client.get(key)
        if data is None:
            return None
        return json.loads(data)

    async def set(self, key: str, value: dict[str, Any]) -> None:
        await self._client.set(key, json.dumps(value))

    # --- Atomic consume operations via Lua scripts ---

    async def atomic_token_bucket(
        self, key: str, max_tokens: int, refill_rate: float
    ) -> dict[str, Any]:
        now = time.time()
        result = await self._client.evalsha(
            self._token_bucket_sha, 1, key, str(max_tokens), str(refill_rate), str(now)
        )
        return _parse_lua_result(result)

    async def atomic_fixed_window(
        self, key: str, max_requests: int, window_seconds: int
    ) -> dict[str, Any]:
        now = time.time()
        window_num = int(now // window_seconds)
        window_key = f"{key}:{window_num}"

        result = await self._client.evalsha(
            self._fixed_window_sha, 1, window_key, str(max_requests), str(window_seconds)
        )
        return _parse_lua_result(result)

    async def atomic_sliding_window(
        self, key: str, max_requests: int, window_seconds: int
    ) -> dict[str, Any]:
        now = time.time()
        # Unique member ID — uuid4 ensures no collisions in the sorted set
        member_id = f"{now}:{uuid.uuid4().hex[:8]}"

        result = await self._client.evalsha(
            self._sliding_window_sha,
            1,
            key,
            str(max_requests),
            str(window_seconds),
            str(now),
            member_id,
        )
        return _parse_lua_result(result)

    async def close(self) -> None:
        await self._client.aclose()


def _parse_lua_result(result: list) -> dict[str, Any]:
    """Parse the [allowed, remaining, retry_after] tuple from Lua scripts."""
    allowed = int(result[0]) == 1
    remaining = float(result[1]) if isinstance(result[1], (bytes, str)) else result[1]
    retry_after_raw = result[2].decode() if isinstance(result[2], bytes) else str(result[2])
    retry_after = None if retry_after_raw == "-1" else float(retry_after_raw)

    return {
        "allowed": allowed,
        "remaining": int(remaining) if remaining == int(remaining) else remaining,
        "retry_after": round(retry_after, 2) if retry_after is not None else None,
    }
