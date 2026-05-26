"""Tests for collector_service.py."""

import asyncio
from contextlib import suppress
import time
from unittest.mock import patch, AsyncMock
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from concept.collector_service import (
    CollectorService,
    AsyncCollectorService,
    CollectorServiceConfig,
    CollectorServiceData,
    ErrorHandlingPolicy,
    get_app,
    zmq_publisher,
)


##############################################################################
#    Test Data and Fixtures
##############################################################################


class SimpleCollectorService(CollectorService[CollectorServiceConfig, CollectorServiceData]):
    """Test implementation of CollectorService."""

    def record(self) -> CollectorServiceData:
        """Simulate recording by sleeping and returning dummy data."""
        time.sleep(0.1)
        return CollectorServiceData()


class SimpleAsyncCollectorService(
    AsyncCollectorService[CollectorServiceConfig, CollectorServiceData]
):
    """Test implementation of CollectorService."""

    async def record(self) -> CollectorServiceData:
        """Simulate recording by sleeping and returning dummy data."""
        await asyncio.sleep(0.1)
        return CollectorServiceData()


##############################################################################
#    Test api app
##############################################################################


sync_app = get_app(
    SimpleCollectorService(
        uid="test_collector", config=CollectorServiceConfig(zmq_addr="tcp://*:35555")
    )
)

async_app = get_app(
    SimpleAsyncCollectorService(
        uid="test_async_collector", config=CollectorServiceConfig(zmq_addr="tcp://*:35556")
    )
)


@pytest.mark.parametrize(
    "app",
    [sync_app, async_app],
)
def test_app(app: FastAPI):
    """Test that the FastAPI app can be created and a request can be made."""
    with TestClient(app) as client:
        response = client.get("/")
        assert response.content == b'"alive"'

        response = client.get("/api/status")
        assert response.json() == {"state": "stopped"}

        response = client.post("/api/start")
        assert response.status_code == 200

        response = client.get("/api/status")
        assert response.json() == {"state": "running"}

        response = client.post("/api/stop")
        assert response.status_code == 200

        response = client.get("/api/status")
        assert response.json() == {"state": "stopped"}


##############################################################################
#    Other tests
##############################################################################


async def test_double_start():
    """Double run start should not cause issues."""
    collector = SimpleCollectorService(
        uid="test_collector_double_start", config=CollectorServiceConfig(zmq_addr="tcp://*:35557")
    )
    async with collector:
        await collector.start()
        await collector.start()


async def test_error_on_start():
    """Test that an error during start is properly raised."""
    with patch.object(
        SimpleCollectorService, "_start_device_pooling_task", side_effect=RuntimeError()
    ):
        collector = SimpleCollectorService(
            uid="test_collector_double_start",
            config=CollectorServiceConfig(zmq_addr="tcp://*:35557"),
        )
        async with collector:
            with pytest.raises(RuntimeError):
                await collector.start()
            assert collector.state == "stopped"


@pytest.mark.parametrize(
    ("cls", "new_callable"),
    [
        (SimpleCollectorService, None),
        (SimpleAsyncCollectorService, AsyncMock),
    ],
)
async def test_device_error(
    cls: type[CollectorService[CollectorServiceConfig, CollectorServiceData]]
    | type[AsyncCollectorService[CollectorServiceConfig, CollectorServiceData]],
    new_callable: None | type[AsyncMock],
):
    """Test that an error during device polling is handled according to the policy."""
    with patch.object(
        cls, new_callable=new_callable, attribute="record", side_effect=RuntimeError
    ) as mock_record:
        # Test STOP policy
        collector = cls(
            uid="test_collector_double_start",
            config=CollectorServiceConfig(
                zmq_addr="tcp://*:35557", device_error_policy=ErrorHandlingPolicy.STOP
            ),
        )

        async with collector:
            await collector.start()
            # Allow some time for the device polling to run and stop
            if collector.device_pooling_task:
                await collector.device_pooling_task
            assert collector.state == "error"

        # Test LOG policy
        collector = cls(
            uid="test_collector_double_start",
            config=CollectorServiceConfig(
                zmq_addr="tcp://*:35557",
                device_error_policy=ErrorHandlingPolicy.LOG,
                device_error_retry_delay_sec=0.1,
            ),
        )

        assert mock_record.call_count == 1

        async with collector:
            await collector.start()
            await asyncio.sleep(0.25)  # Allow some time for the device polling to run and retry
            assert mock_record.call_count > 2


async def test_zmq_publisher_loop():
    """Test that zmq_publisher is actually an infinite loop that can be cancelled."""
    # This test is for code coverage purposes ;)
    queue = AsyncMock()
    zmq_socket = AsyncMock()

    queue.get = AsyncMock(return_value=CollectorServiceData())
    zmq_socket.send_json = AsyncMock(side_effect=RuntimeError)

    task = asyncio.create_task(zmq_publisher("uid1", queue, zmq_socket))
    await asyncio.sleep(0.25)  # let it enter several iterations of the loop
    task.cancel()

    with suppress(asyncio.CancelledError):
        await task

    assert zmq_socket.send_json.call_count > 1

    # # assert zmq_socket.send_json.called
