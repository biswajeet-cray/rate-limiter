from unittest.mock import patch

from algorithms.fixed_window import FixedWindow, FixedWindowResult
from storage.memory_backend import MemoryBackend


def make_window(max_requests: int = 5, window_seconds: int = 60) -> FixedWindow:
    return FixedWindow(
        max_requests=max_requests,
        window_seconds=window_seconds,
        storage=MemoryBackend(),
    )


# --- Basic allow / deny ---


async def test_first_request_allowed():
    fw = make_window(max_requests=5)
    result = await fw.consume("user1")
    assert result.allowed is True
    assert result.remaining_requests == 4
    assert result.retry_after is None


async def test_requests_allowed_until_limit():
    fw = make_window(max_requests=3)
    for i in range(3):
        result = await fw.consume("user1")
        assert result.allowed is True
        assert result.remaining_requests == 2 - i

    result = await fw.consume("user1")
    assert result.allowed is False
    assert result.remaining_requests == 0
    assert result.retry_after is not None
    assert result.retry_after > 0


async def test_denied_has_positive_retry_after():
    fw = make_window(max_requests=1, window_seconds=30)
    await fw.consume("user1")

    result = await fw.consume("user1")
    assert result.allowed is False
    assert result.retry_after is not None
    assert 0 < result.retry_after <= 30


# --- Window rollover ---


async def test_window_resets_after_rollover():
    fw = make_window(max_requests=2, window_seconds=10)

    # Use a fixed time so we can control the window boundary
    with patch("algorithms.fixed_window.time") as mock_time:
        # t=100 -> window 10
        mock_time.monotonic.return_value = 100.0
        await fw.consume("user1")
        await fw.consume("user1")
        result = await fw.consume("user1")
        assert result.allowed is False

        # t=110 -> window 11 (new window, counter resets)
        mock_time.monotonic.return_value = 110.0
        result = await fw.consume("user1")
        assert result.allowed is True
        assert result.remaining_requests == 1


async def test_multiple_window_rollovers():
    fw = make_window(max_requests=1, window_seconds=10)

    with patch("algorithms.fixed_window.time") as mock_time:
        # Window 10: use the single allowed request
        mock_time.monotonic.return_value = 100.0
        result = await fw.consume("user1")
        assert result.allowed is True

        # Still in window 10: denied
        mock_time.monotonic.return_value = 105.0
        result = await fw.consume("user1")
        assert result.allowed is False

        # Window 11: allowed again
        mock_time.monotonic.return_value = 110.0
        result = await fw.consume("user1")
        assert result.allowed is True

        # Window 12: allowed again
        mock_time.monotonic.return_value = 120.0
        result = await fw.consume("user1")
        assert result.allowed is True


# --- Boundary behavior ---


async def test_request_at_exact_window_boundary():
    """A request exactly at a window boundary falls into the new window."""
    fw = make_window(max_requests=1, window_seconds=10)

    with patch("algorithms.fixed_window.time") as mock_time:
        # Exhaust window 10
        mock_time.monotonic.return_value = 100.0
        await fw.consume("user1")

        # Exactly at boundary of window 11
        mock_time.monotonic.return_value = 110.0
        result = await fw.consume("user1")
        assert result.allowed is True


async def test_retry_after_reflects_time_to_next_window():
    fw = make_window(max_requests=1, window_seconds=10)

    with patch("algorithms.fixed_window.time") as mock_time:
        # t=103 -> window 10 (starts at 100, ends at 110)
        mock_time.monotonic.return_value = 103.0
        await fw.consume("user1")

        # Denied at t=105 -> should retry in ~5 seconds (until t=110)
        mock_time.monotonic.return_value = 105.0
        result = await fw.consume("user1")
        assert result.allowed is False
        assert result.retry_after is not None
        assert abs(result.retry_after - 5.0) < 0.01


async def test_denied_multiple_times_same_window():
    """Multiple denied requests in the same window don't corrupt state."""
    fw = make_window(max_requests=1, window_seconds=10)

    with patch("algorithms.fixed_window.time") as mock_time:
        mock_time.monotonic.return_value = 100.0
        await fw.consume("user1")

        # Denied 3 times — all should behave consistently
        for t in [101.0, 103.0, 107.0]:
            mock_time.monotonic.return_value = t
            result = await fw.consume("user1")
            assert result.allowed is False
            assert result.remaining_requests == 0

        # New window: should still work
        mock_time.monotonic.return_value = 110.0
        result = await fw.consume("user1")
        assert result.allowed is True


# --- Multiple keys ---


async def test_independent_keys():
    fw = make_window(max_requests=2)

    # Exhaust user1
    await fw.consume("user1")
    await fw.consume("user1")
    result = await fw.consume("user1")
    assert result.allowed is False

    # user2 is unaffected
    result = await fw.consume("user2")
    assert result.allowed is True
    assert result.remaining_requests == 1


async def test_many_keys_independent():
    fw = make_window(max_requests=3)

    keys = ["key_a", "key_b", "key_c"]
    for key in keys:
        result = await fw.consume(key)
        assert result.allowed is True
        assert result.remaining_requests == 2

    # Exhaust key_a
    await fw.consume("key_a")
    await fw.consume("key_a")
    result = await fw.consume("key_a")
    assert result.allowed is False

    # Others still have capacity
    for key in ["key_b", "key_c"]:
        result = await fw.consume(key)
        assert result.allowed is True


# --- Edge cases ---


async def test_result_dataclass():
    result = FixedWindowResult(allowed=True, remaining_requests=9, retry_after=None)
    assert result.allowed is True
    assert result.remaining_requests == 9


async def test_single_request_limit():
    fw = make_window(max_requests=1)
    result = await fw.consume("user1")
    assert result.allowed is True
    assert result.remaining_requests == 0

    result = await fw.consume("user1")
    assert result.allowed is False
