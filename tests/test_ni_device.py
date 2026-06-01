from unittest.mock import MagicMock
from unittest.mock import patch

import numpy as np
import pytest

from concept.ni_collector_service import (
    NICollectorConfig,
    NICollectorData,
    NIDevice,
)


@pytest.fixture
def config() -> NICollectorConfig:
    return NICollectorConfig(
        channel="Dev1/ai0", sample_rate=1000, samples_per_read=100, zmq_addr="1.1.1.1"
    )


@patch("concept.ni_collector_service.AnalogSingleChannelReader")
@patch("concept.ni_collector_service.nidaqmx.Task")
def test_connect(
    mock_task_cls,
    mock_reader_cls,
    config: NICollectorConfig,
):
    mock_task = MagicMock()

    mock_task_cls.return_value = mock_task

    mock_reader = MagicMock()

    mock_reader_cls.return_value = mock_reader

    device = NIDevice(config)

    device.connect()

    mock_task.ai_channels.add_ai_voltage_chan.assert_called_once_with(
        config.channel,
    )

    mock_task.timing.cfg_samp_clk_timing.assert_called_once()

    mock_task.start.assert_called_once()

    assert device.task is mock_task

    assert device.reader is mock_reader

    assert isinstance(device.buffer, np.ndarray)

    assert len(device.buffer) == config.samples_per_read


def test_read_success(config: NICollectorConfig):

    device = NIDevice(config)

    buffer = np.array(
        [1.0, 2.0, 3.0],
        dtype=np.float64,
    )

    reader = MagicMock()

    device.buffer = buffer

    device.reader = reader

    result = device.read()

    reader.read_many_sample.assert_called_once()

    assert isinstance(result, NICollectorData)

    assert result.samples == [1.0, 2.0, 3.0]


def test_read_without_reader(config: NICollectorConfig):

    device = NIDevice(config)

    device.buffer = np.zeros(100)

    with pytest.raises(RuntimeError):
        device.read()


def test_read_without_buffer(config: NICollectorConfig):

    device = NIDevice(config)

    device.reader = MagicMock()

    with pytest.raises(RuntimeError):
        device.read()


def test_disconnect(config: NICollectorConfig):

    device = NIDevice(config)

    task = MagicMock()

    device.task = task

    device.reader = MagicMock()

    device.buffer = np.zeros(100)

    device.disconnect()

    task.stop.assert_called_once()

    task.close.assert_called_once()

    assert device.task is None

    assert device.reader is None

    assert device.buffer is None


def test_disconnect_without_connect(config: NICollectorConfig):

    device = NIDevice(config)

    device.disconnect()

    assert device.task is None


@pytest.mark.integration
def test_real_device_read(config: NICollectorConfig):
    device = NIDevice(config)

    device.connect()

    try:
        data = device.read()

        assert len(data.samples) == 100

    finally:
        device.disconnect()
