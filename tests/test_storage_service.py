"""Tests for storage_service.py."""

import asyncio
from typing import Any
import pytest

from concept.storage_service import (
    CollectorMessage,
    _put_nowait_with_drop,
    write_db_from_queue,
)  # type: ignore[import]


def msg(n: int) -> CollectorMessage[Any]:
    """Helper to create a CollectorMessage with given uid and empty data."""
    return CollectorMessage(uid=str(n), data={})


def test_put_nowait_drops_oldest_when_full():
    """When the queue is full, the oldest item is dropped to make space for new data."""
    q: asyncio.Queue[CollectorMessage[Any]] = asyncio.Queue(maxsize=2)
    _put_nowait_with_drop(q, msg(1))
    _put_nowait_with_drop(q, msg(2))
    _put_nowait_with_drop(q, msg(3))  # full — drops msg(1), inserts msg(3)
    assert q.qsize() == 2
    items = [q.get_nowait(), q.get_nowait()]
    assert {i["uid"] for i in items} == {"2", "3"}


@pytest.mark.asyncio
async def test_write_db_from_queue_continues_after_error():
    """Exception in write_fn is swallowed; next message is still processed."""
    results: list[str] = []

    async def write_fn(data: CollectorMessage[Any]) -> None:
        if data["uid"] == "bad":
            raise RuntimeError("boom")
        results.append(data["uid"])

    bad: CollectorMessage[Any] = CollectorMessage(uid="bad", data={})
    q: asyncio.Queue[CollectorMessage[Any]] = asyncio.Queue()
    await q.put(msg(0))
    await q.put(bad)
    await q.put(msg(2))

    task = asyncio.create_task(write_db_from_queue(q, write_fn))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert results == ["0", "2"]
