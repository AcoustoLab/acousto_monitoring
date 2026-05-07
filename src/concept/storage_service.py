"""Storage service abstractions."""

from abc import ABC, abstractmethod
from typing import Any

import zmq.asyncio

from pydantic import BaseModel


class AbstractDatabase(ABC):
    """Abstract database class."""

    @abstractmethod
    async def status(self) -> dict[str, Any]:
        """Get database status."""


class StorageServiceConfig(BaseModel):
    """Storage service configuration."""


class AbstractStorageService(ABC):
    """Abstract storage service class."""

    def __init__(self, config: StorageServiceConfig):
        self._config = config
        self._local_db = None
        self._remote_db = None
        self._zmq_ctx = zmq.asyncio.Context()
        self._pull_socket = None

    @abstractmethod
    async def sync(self, data: dict[str, Any]):
        """Sync data."""

    @abstractmethod
    async def start(self):
        """Start the storage service."""

    @abstractmethod
    async def stop(self):
        """Stop the storage service."""

    @abstractmethod
    async def status(self) -> dict[str, Any]:
        """Get storage service status."""
