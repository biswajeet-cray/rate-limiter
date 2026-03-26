from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
    """Abstract storage backend for rate limiter state.

    Think of this like IRepository<T> in .NET — it defines the contract
    that both in-memory and Redis backends must implement.
    """

    @abstractmethod
    async def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve bucket state for a key. Returns None if key doesn't exist."""

    @abstractmethod
    async def set(self, key: str, value: dict[str, Any]) -> None:
        """Store bucket state for a key."""
