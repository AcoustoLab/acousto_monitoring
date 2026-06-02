"""Tests for storage_service."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from concept.collector_service import CollectorServiceData
from concept.storage_service import (
    AbstractStorageService,
    CollectorMessage,
    StorageServiceConfig,
    _put_nowait_with_drop,  # type: ignore
    listen_to_zmq_queue,
    write_db_from_queue,
)


def msg(uid: str) -> CollectorMessage[Any]:
    """Helper to create a CollectorMessage with given uid."""
    return CollectorMessage(uid=uid, data={})


class DummyStorage(AbstractStorageService[StorageServiceConfig, CollectorServiceData]):
    """Dummy storage service for testing AbstractStorageService logic without real storage."""

    def _connect_db(self) -> None: ...
    async def write_db(self, data: CollectorMessage[CollectorServiceData]) -> None: ...
    async def sync(self, data: CollectorServiceData) -> None: ...
    async def status(self) -> dict[str, Any]: return {}


@pytest.fixture()
def storage() -> DummyStorage:
    """Fixture to create a DummyStorage instance for testing."""
    return DummyStorage(StorageServiceConfig(zmq_sub_addrs=["tcp://localhost:5555"]))


def test_put_inserts_when_space_available() -> None:
    """Test that _put_nowait_with_drop inserts items when queue is not full."""
    q: asyncio.Queue[CollectorMessage[Any]] = asyncio.Queue(maxsize=2)
    _put_nowait_with_drop(q, msg("1"))
    assert q.qsize() == 1


def test_put_drops_oldest_when_full() -> None:
    """Test that _put_nowait_with_drop drops the oldest item when the queue is full."""
    q: asyncio.Queue[CollectorMessage[Any]] = asyncio.Queue(maxsize=2)
    _put_nowait_with_drop(q, msg("1"))
    _put_nowait_with_drop(q, msg("2"))
    _put_nowait_with_drop(q, msg("3"))  # "1" dropped, "3" inserted
    assert {q.get_nowait()["uid"], q.get_nowait()["uid"]} == {"2", "3"}


@pytest.mark.asyncio
async def test_listen_puts_valid_message_in_queue() -> None:
    """Test that listen_to_zmq_queue puts valid JSON messages in the queue."""
    socket = AsyncMock()
    socket.recv.side_effect = [b'{"uid":"x","data":{}}', asyncio.CancelledError()]

    q: asyncio.Queue[CollectorMessage[Any]] = asyncio.Queue()
    with pytest.raises(asyncio.CancelledError):
        await listen_to_zmq_queue(socket, q)

    assert q.get_nowait()["uid"] == "x"


@pytest.mark.asyncio
async def test_listen_swallows_bad_json_and_continues() -> None:
    """Test that listen_to_zmq_queue ignores invalid JSON and continues listening."""
    socket = AsyncMock()
    socket.recv.side_effect = [b"not json", b'{"uid":"y","data":{}}', asyncio.CancelledError()]

    q: asyncio.Queue[CollectorMessage[Any]] = asyncio.Queue()
    with pytest.raises(asyncio.CancelledError):
        await listen_to_zmq_queue(socket, q)

    assert q.get_nowait()["uid"] == "y"


@pytest.mark.asyncio
async def test_write_processes_message() -> None:
    """Test that write_db_from_queue calls the write function with messages from the queue."""
    writes: list[str] = []

    async def write_fn(data: CollectorMessage[Any]) -> None:
        writes.append(data["uid"])

    q: asyncio.Queue[CollectorMessage[Any]] = asyncio.Queue()
    await q.put(msg("a"))

    task = asyncio.create_task(write_db_from_queue(q, write_fn))
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert writes == ["a"]


@pytest.mark.asyncio
async def test_write_continues_after_exception() -> None:
    """Test that write_db_from_queue continues processing even if the write raises exception."""
    writes: list[str] = []

    async def write_fn(data: CollectorMessage[Any]) -> None:
        if data["uid"] == "bad":
            raise RuntimeError("boom")
        writes.append(data["uid"])

    q: asyncio.Queue[CollectorMessage[Any]] = asyncio.Queue()
    await q.put(msg("bad"))
    await q.put(msg("ok"))

    task = asyncio.create_task(write_db_from_queue(q, write_fn))
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert writes == ["ok"]


@pytest.mark.asyncio
async def test_start_creates_tasks(storage: DummyStorage) -> None:
    """Test that start() creates the listening and writing tasks."""
    with patch("concept.storage_service.zmq.asyncio.Context"):
        await storage.start()
        assert storage._writing_task is not None  # type: ignore
        assert not storage._writing_task.done()  # type: ignore
        await storage.stop()


@pytest.mark.asyncio
async def test_start_is_idempotent(storage: DummyStorage) -> None:
    """Test that second start() call is a no-op when already running."""
    with patch("concept.storage_service.zmq.asyncio.Context"):
        await storage.start()
        first_task = storage._writing_task  # type: ignore
        await storage.start()  # second call should be a no-op
        assert storage._writing_task is first_task  # type: ignore
        await storage.stop()


@pytest.mark.asyncio
async def test_stop_clears_all_state(storage: DummyStorage) -> None:
    """Test that stop() cancels tasks and clears zmq sockets and context."""
    with patch("concept.storage_service.zmq.asyncio.Context"):
        await storage.start()
        await storage.stop()

    assert storage._writing_task is None  # type: ignore
    assert storage._listening_tasks == []  # type: ignore
    assert storage._sub_sockets == []  # type: ignore
    assert storage._zmq_ctx is None  # type: ignore


@pytest.mark.asyncio
async def test_stop_without_start_is_safe(storage: DummyStorage) -> None:
    """Test that calling stop() without start() does not raise exceptions."""
    await storage.stop()
    assert storage._writing_task is None  # type: ignore
