from typing import Any

from storage.base import StorageBackend


class MemoryBackend(StorageBackend):
    """In-memory storage backend using a plain dict.

    Good for testing and single-process deployments.
    Not shared across processes — for distributed use, see RedisBackend.
    """

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self._data.get(key)

    async def set(self, key: str, value: dict[str, Any]) -> None:
        self._data[key] = value
