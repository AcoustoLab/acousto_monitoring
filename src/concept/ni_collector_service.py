"""Collector service for NI devices."""

import numpy as np
import nidaqmx
from .collector_service import CollectorService, CollectorServiceConfig, CollectorServiceData
from nidaqmx.stream_readers import AnalogSingleChannelReader


class NICollectorConfig(CollectorServiceConfig):
    channel: str = "Dev1/ai0"
    sample_rate: float = 10_000
    samples_per_read: int = 1000


class NICollectorData(CollectorServiceData):
    samples: list[float]


class NIDevice:
    """Thin wrapper around NI-DAQmx hardware session."""

    def __init__(self, config: NICollectorConfig):
        self.config = config

        self.task: nidaqmx.Task | None = None

        self.reader: AnalogSingleChannelReader | None = None

        self.buffer: np.ndarray | None = None

    def connect(self):
        """Create and configure persistent NI task."""
        task = nidaqmx.Task()

        # == Configure analog input channel ==
        task.ai_channels.add_ai_voltage_chan(
            self.config.channel,
        )

        # == Configure continuous acquisition ==
        task.timing.cfg_samp_clk_timing(
            rate=self.config.sample_rate,
            sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS,
            samps_per_chan=self.config.samples_per_read * 10,
        )

        # == Optimized stream reader ==
        reader = AnalogSingleChannelReader(
            task.in_stream,
        )

        # == Preallocated acquisition buffer ==
        buffer = np.zeros(
            self.config.samples_per_read,
            dtype=np.float64,
        )

        # == Start acquisition ==
        task.start()

        self.task = task
        self.reader = reader
        self.buffer = buffer

    def read(self) -> NICollectorData:
        """Read chunk from hardware buffer."""
        if self.reader is None:
            raise RuntimeError("Reader is not initialized")

        if self.buffer is None:
            raise RuntimeError("Buffer is not initialized")

        self.reader.read_many_sample(
            self.buffer,
            number_of_samples_per_channel=len(self.buffer),
        )

        return NICollectorData(
            samples=self.buffer.tolist(),
        )

    def disconnect(self):
        """Close hardware session."""
        if self.task is not None:
            self.task.stop()
            self.task.close()

        self.task = None
        self.reader = None
        self.buffer = None


class NICollectorService(CollectorService[CollectorServiceConfig, CollectorServiceData]):
    """NI device implementation of CollectorService."""

    def __init__(
        self,
        uid: str,
        config: NICollectorConfig,
    ):
        super().__init__(
            uid=uid,
            config=config,
        )

        # Device object exists during collector lifetime,
        # but hardware session is opened only in __aenter__
        self.device = NIDevice(config)

    async def __aenter__(self):
        """Async context manager entry point.

        Start a publishing task that listens for device data and sends it to zmq.
        """
        await super().__aenter__()
        self.device.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):  # type: ignore
        """Async context manager exit point.

        Stop the collector and cancel the publishing task.
        """
        self.device.disconnect()
        await super().__aexit__(
            exc_type,
            exc_val,
            exc_tb,
        )  # type: ignore

    def record(self) -> CollectorServiceData:
        """Simulate recording by sleeping and returning dummy data."""
        return self.device.read()
