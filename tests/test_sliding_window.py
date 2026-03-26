from unittest.mock import patch

from algorithms.sliding_window import SlidingWindow, SlidingWindowResult
from storage.memory_backend import MemoryBackend


def make_window(max_requests: int = 5, window_seconds: int = 60) -> SlidingWindow:
    return SlidingWindow(
        max_requests=max_requests,
        window_seconds=window_seconds,
        storage=MemoryBackend(),
    )


# --- Basic allow / deny ---


async def test_first_request_allowed():
    sw = make_window(max_requests=5)
    result = await sw.consume("user1")
    assert result.allowed is True
    assert result.remaining_requests == 4
    assert result.retry_after is None


async def test_requests_allowed_until_limit():
    sw = make_window(max_requests=3)
    for i in range(3):
        result = await sw.consume("user1")
        assert result.allowed is True
        assert result.remaining_requests == 2 - i

    result = await sw.consume("user1")
    assert result.allowed is False
    assert result.remaining_requests == 0
    assert result.retry_after is not None
    assert result.retry_after > 0


async def test_denied_has_retry_after():
    sw = make_window(max_requests=1, window_seconds=30)

    with patch("algorithms.sliding_window.time") as mock_time:
        mock_time.monotonic.return_value = 100.0
        await sw.consume("user1")

        mock_time.monotonic.return_value = 110.0
        result = await sw.consume("user1")
        assert result.allowed is False
        # Oldest request at t=100, expires at t=130 -> retry_after = 20
        assert result.retry_after is not None
        assert abs(result.retry_after - 20.0) < 0.01


# --- Sliding behavior (requests expire out of window) ---


async def test_old_requests_expire():
    """Requests older than window_seconds are pruned, freeing up capacity."""
    sw = make_window(max_requests=2, window_seconds=10)

    with patch("algorithms.sliding_window.time") as mock_time:
        # Two requests at t=100
        mock_time.monotonic.return_value = 100.0
        await sw.consume("user1")
        await sw.consume("user1")

        # Denied at t=105 (both still in window)
        mock_time.monotonic.return_value = 105.0
        result = await sw.consume("user1")
        assert result.allowed is False

        # At t=111, both requests from t=100 have expired (>10s ago)
        mock_time.monotonic.return_value = 111.0
        result = await sw.consume("user1")
        assert result.allowed is True
        assert result.remaining_requests == 1


async def test_partial_expiry():
    """Only expired requests are pruned — newer ones stay."""
    sw = make_window(max_requests=2, window_seconds=10)

    with patch("algorithms.sliding_window.time") as mock_time:
        # Request at t=100
        mock_time.monotonic.return_value = 100.0
        await sw.consume("user1")

        # Request at t=106
        mock_time.monotonic.return_value = 106.0
        await sw.consume("user1")

        # Denied at t=108 (both in window)
        mock_time.monotonic.return_value = 108.0
        result = await sw.consume("user1")
        assert result.allowed is False

        # At t=111: request from t=100 expired, t=106 still active -> 1 slot open
        mock_time.monotonic.return_value = 111.0
        result = await sw.consume("user1")
        assert result.allowed is True
        assert result.remaining_requests == 0  # now at capacity

        # Still denied for one more
        result = await sw.consume("user1")
        assert result.allowed is False


async def test_no_fixed_window_boundary_problem():
    """Unlike fixed window, sliding window prevents 2x burst at boundaries.

    Fixed window flaw: 5 requests at t=59 + 5 at t=60 = 10 in 2 seconds.
    Sliding window: the 5 from t=59 are still in the window at t=60.
    """
    sw = make_window(max_requests=5, window_seconds=60)

    with patch("algorithms.sliding_window.time") as mock_time:
        # 5 requests at t=59 (near "boundary" in fixed window terms)
        mock_time.monotonic.return_value = 59.0
        for _ in range(5):
            result = await sw.consume("user1")
            assert result.allowed is True

        # At t=60: all 5 from t=59 are still in the 60s window -> denied
        mock_time.monotonic.return_value = 60.0
        result = await sw.consume("user1")
        assert result.allowed is False


async def test_gradual_expiry_over_time():
    sw = make_window(max_requests=3, window_seconds=10)

    with patch("algorithms.sliding_window.time") as mock_time:
        # Stagger 3 requests: t=100, t=103, t=106
        for t in [100.0, 103.0, 106.0]:
            mock_time.monotonic.return_value = t
            await sw.consume("user1")

        # At t=109: all 3 in window -> denied
        mock_time.monotonic.return_value = 109.0
        result = await sw.consume("user1")
        assert result.allowed is False

        # At t=111: t=100 expired -> 2 in window, 1 slot open
        mock_time.monotonic.return_value = 111.0
        result = await sw.consume("user1")
        assert result.allowed is True
        assert result.remaining_requests == 0


# --- Burst handling ---


async def test_burst_capacity():
    """All max_requests can be used at once (burst), then denied."""
    sw = make_window(max_requests=10, window_seconds=60)

    with patch("algorithms.sliding_window.time") as mock_time:
        mock_time.monotonic.return_value = 100.0
        for _ in range(10):
            result = await sw.consume("user1")
            assert result.allowed is True

        result = await sw.consume("user1")
        assert result.allowed is False


async def test_burst_then_gradual_recovery():
    """After a burst, slots open one-by-one as old requests expire."""
    sw = make_window(max_requests=3, window_seconds=10)

    with patch("algorithms.sliding_window.time") as mock_time:
        # Burst 3 requests at t=100, t=101, t=102
        for t in [100.0, 101.0, 102.0]:
            mock_time.monotonic.return_value = t
            await sw.consume("user1")

        # Denied at t=105
        mock_time.monotonic.return_value = 105.0
        result = await sw.consume("user1")
        assert result.allowed is False

        # t=111: cutoff=101, so t=100 and t=101 both expire -> only t=102 remains
        mock_time.monotonic.return_value = 111.0
        result = await sw.consume("user1")
        assert result.allowed is True
        assert result.remaining_requests == 1  # 102 + new at 111 = 2 of 3

        # t=113: cutoff=103, t=102 expires -> only t=111 remains
        mock_time.monotonic.return_value = 113.0
        result = await sw.consume("user1")
        assert result.allowed is True
        assert result.remaining_requests == 1  # 111 + new at 113 = 2 of 3


# --- Memory cleanup ---


async def test_expired_timestamps_are_pruned_from_storage():
    """Pruned timestamps are not stored — prevents unbounded memory growth."""
    sw = make_window(max_requests=5, window_seconds=10)

    with patch("algorithms.sliding_window.time") as mock_time:
        # Add 5 requests at t=100
        mock_time.monotonic.return_value = 100.0
        for _ in range(5):
            await sw.consume("user1")

        state = await sw.storage.get("user1")
        assert len(state["timestamps"]) == 5

        # At t=111, all expired — next consume prunes them
        mock_time.monotonic.return_value = 111.0
        await sw.consume("user1")

        state = await sw.storage.get("user1")
        assert len(state["timestamps"]) == 1  # only the new request


async def test_denied_request_still_prunes():
    """Even denied requests trigger pruning of expired timestamps."""
    sw = make_window(max_requests=2, window_seconds=10)

    with patch("algorithms.sliding_window.time") as mock_time:
        # 2 requests at t=100, plus some old expired ones simulated
        mock_time.monotonic.return_value = 100.0
        await sw.consume("user1")
        await sw.consume("user1")

        # Inject an old timestamp manually to simulate stale data
        state = await sw.storage.get("user1")
        state["timestamps"].insert(0, 50.0)  # well outside window
        await sw.storage.set("user1", state)

        # At t=105: the t=50 entry gets pruned, leaving 2 from t=100 -> denied
        mock_time.monotonic.return_value = 105.0
        result = await sw.consume("user1")
        assert result.allowed is False

        # Verify stale entry was pruned
        state = await sw.storage.get("user1")
        assert all(ts >= 100.0 for ts in state["timestamps"])


# --- Multiple keys ---


async def test_independent_keys():
    sw = make_window(max_requests=2)

    await sw.consume("user1")
    await sw.consume("user1")
    result = await sw.consume("user1")
    assert result.allowed is False

    result = await sw.consume("user2")
    assert result.allowed is True
    assert result.remaining_requests == 1


async def test_many_keys_independent():
    sw = make_window(max_requests=3)

    for key in ["key_a", "key_b", "key_c"]:
        result = await sw.consume(key)
        assert result.allowed is True
        assert result.remaining_requests == 2

    # Exhaust key_a
    await sw.consume("key_a")
    await sw.consume("key_a")
    result = await sw.consume("key_a")
    assert result.allowed is False

    for key in ["key_b", "key_c"]:
        result = await sw.consume(key)
        assert result.allowed is True


# --- Edge cases ---


async def test_result_dataclass():
    result = SlidingWindowResult(allowed=True, remaining_requests=4, retry_after=None)
    assert result.allowed is True
    assert result.remaining_requests == 4


async def test_single_request_limit():
    sw = make_window(max_requests=1, window_seconds=10)

    with patch("algorithms.sliding_window.time") as mock_time:
        mock_time.monotonic.return_value = 100.0
        result = await sw.consume("user1")
        assert result.allowed is True
        assert result.remaining_requests == 0

        result = await sw.consume("user1")
        assert result.allowed is False
