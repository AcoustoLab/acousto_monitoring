"""Storage service abstractions."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
import json
from typing import Any, TypeVar, Generic
import zmq.asyncio
import asyncio

from pydantic import BaseModel
import logging


logger = logging.getLogger(__file__)


def _put_nowait_with_drop(
    queue: asyncio.Queue[dict[str, Any]],
    data: dict[str, Any],
) -> None:
    """Put data in the queue, dropping old data if the queue is full."""
    try:
        queue.put_nowait(data)
    except asyncio.QueueFull:
        logger.warning(
            "Queue full, dropping data",
        )
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                queue.put_nowait(data)
                break


async def listen_to_zmq_queue(
    socket: zmq.asyncio.Socket,
    queue: asyncio.Queue[dict[str, Any]],
) -> None:
    """Listen to zmq for incoming data and put it in the queue."""
    while True:
        try:
            data = json.loads((await socket.recv()).decode("utf-8"))
            _put_nowait_with_drop(queue, data)
        except Exception:
            logger.error("Error receiving data from zmq")


async def write_db_from_queue(
    queue: asyncio.Queue[dict[str, Any]],
    write_db_fn: Callable[[dict[str, Any]], Awaitable[None]]
) -> None:
    """Write data from queue to database."""
    while True:
        data = await queue.get()
        await write_db_fn(data)


class AbstractDatabase(ABC):
    """Abstract database class."""

    @abstractmethod
    async def status(self) -> dict[str, Any]:
        """Get database status."""


class StorageServiceConfig(BaseModel):
    """Storage service configuration."""

    zmq_sub_addrs: list[str]


class AbstractStorageService[StorageServiceConfigT: StorageServiceConfig](ABC):
    """Abstract storage service class."""

    def __init__(self, config: StorageServiceConfigT):
        self._config = config
        self._db = None

        self._zmq_ctx = zmq.asyncio.Context()
        self._sub_sockets: list[zmq.asyncio.Socket] = []
        self._listening_tasks: list[asyncio.Task[None]] = []
        self._writing_task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        self._connect_db()
        self._zmq_addrs = list(self._config.zmq_sub_addrs)
        for zmq_addr in self._zmq_addrs:
            self._add_zmq_subcription(zmq_addr)

    def _add_zmq_subcription(self, zmq_addr: str):
        """Add a zmq subscriber (synchronous)."""
        sub_socket = self._zmq_ctx.socket(zmq.SUB)
        sub_socket.bind(zmq_addr)
        sub_socket.setsockopt_string(zmq.SUBSCRIBE, "")
        self._sub_sockets.append(sub_socket)

    @abstractmethod
    def _connect_db(self):
        """Connect to the database."""

    @abstractmethod
    async def write_db(self, data: dict[str, Any]):
        """Write data to the database."""

    @abstractmethod
    async def sync(self, data: dict[str, Any]):
        """Sync data."""

    async def start(self):
        """Start the storage service."""
        for sub_socket in self._sub_sockets:
            listening_task = asyncio.create_task(
                listen_to_zmq_queue(sub_socket, self._queue),
            )
            self._listening_tasks.append(listening_task)

        self._writing_task = asyncio.create_task(
            write_db_from_queue(self._queue, self.write_db)
        )

    async def stop(self):
        """Stop the storage service."""
        for task in self._listening_tasks:
            task.cancel()
        if self._writing_task:
            self._writing_task.cancel()

    @abstractmethod
    async def status(self) -> dict[str, Any]:
        """Get storage service status."""
