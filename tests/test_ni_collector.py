import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from concept.ni_collector_service import (
    NICollectorConfig,
    NICollectorData,
    NICollectorService,
)


@pytest.fixture
def config():
    return NICollectorConfig(
        channel="Dev1/ai0",
        sample_rate=1000,
        samples_per_read=10,
        zmq_addr="tcp://127.0.0.1:5554",
    )


class FakeDevice:
    def __init__(self):
        self.connected = False

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def read(self):
        return NICollectorData(
            samples=[1.0, 2.0, 3.0],
        )


@pytest.mark.asyncio
async def test_context_manager(config: NICollectorConfig):

    collector = NICollectorService(
        uid="test",
        config=config,
    )

    fake_device = FakeDevice()

    collector.device = fake_device

    async with collector:
        assert fake_device.connected is True

    assert fake_device.connected is False


@pytest.mark.asyncio
async def test_record(config: NICollectorConfig):

    collector = NICollectorService(
        uid="test",
        config=config,
    )
    fake_device = FakeDevice()
    collector.device = fake_device

    result = collector.record()
    print(result.samples)
    assert result.samples == [1.0, 2.0, 3.0]


@pytest.mark.asyncio
async def test_start_and_stop(config):

    collector = NICollectorService(
        uid="test",
        config=config,
    )

    collector.device = FakeDevice()

    async with collector:
        await collector.start()

        await asyncio.sleep(0.05)

        assert collector.device_pooling_task is not None

        await collector.stop()

        assert collector.device_pooling_task is None


@pytest.mark.asyncio
async def test_queue_receives_data(config: NICollectorConfig):

    collector = NICollectorService(
        uid="test",
        config=config,
    )

    collector.device = FakeDevice()

    async with collector:
        await collector.start()

        data = await asyncio.wait_for(
            collector.device_queue.get(),
            timeout=1,
        )

        assert data.samples == [1.0, 2.0, 3.0]

        await collector.stop()


@pytest.mark.asyncio
async def test_multiple_starts_are_safe(config: NICollectorConfig):

    collector = NICollectorService(
        uid="test",
        config=config,
    )

    collector.device = FakeDevice()

    async with collector:
        await collector.start()

        first_task = collector.device_pooling_task

        await collector.start()

        second_task = collector.device_pooling_task

        assert first_task is second_task

        await collector.stop()


@pytest.mark.asyncio
async def test_stop_without_start(config: NICollectorConfig):

    collector = NICollectorService(
        uid="test",
        config=config,
    )

    collector.device = FakeDevice()

    async with collector:
        await collector.stop()

        assert collector.device_pooling_task is None
