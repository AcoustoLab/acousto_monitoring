"""Tests for the storage service."""

import asyncio
from unittest.mock import MagicMock
import sys

from typing import Any

from concept.storage_service import _put_nowait_with_drop, CollectorMessage  # type: ignore


sys.modules.setdefault("zmq", MagicMock())
sys.modules.setdefault("zmq.asyncio", MagicMock())


def make_msg(n: int) -> CollectorMessage[Any]:
    """Make a dummy CollectorMessage."""
    return CollectorMessage(uid=str(n), data={})


def test_put_nowait_with_drop_normal():
    """Item goes in when queue has room."""
    q: asyncio.Queue[CollectorMessage[Any]] = asyncio.Queue(maxsize=3)
    _put_nowait_with_drop(q, make_msg(1))
    assert q.qsize() == 1


def test_put_nowait_with_drop_full():
    """When queue is full the oldest item is dropped and new one inserted."""
    q: asyncio.Queue[CollectorMessage[Any]] = asyncio.Queue(maxsize=2)
    _put_nowait_with_drop(q, make_msg(1))
    _put_nowait_with_drop(q, make_msg(2))
    # queue is now full; next call should drop one and insert new
    _put_nowait_with_drop(q, make_msg(3))
    assert q.qsize() == 2
    # the latest item must be present
    items = [q.get_nowait(), q.get_nowait()]
    uids = {i["uid"] for i in items}
    assert "3" in uids
