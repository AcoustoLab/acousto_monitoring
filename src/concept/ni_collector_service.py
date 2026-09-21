"""Collector service for NI devices."""

import numpy as np
from .collector_service import CollectorService, CollectorServiceConfig, CollectorServiceData
from nidaqmx.stream_readers import AnalogSingleChannelReader, AnalogMultiChannelReader
from nidaqmx.constants import (
    Coupling,
    ExcitationSource,
    AcquisitionType,
)
from nidaqmx.task._task import Task
from concept.pydantic_serializers import SerializedNDArray
from dataclasses import dataclass, field
from typing import Annotated


@dataclass
class NIChannelConfig:
    """
    Configuration for a single NI channel.

    Do not forget to set the excitation current for IEPE sensors(e.g. mics, accelerometers).
    """

    channel: str
    iepe: bool = False
    iepe_current: float = 0.0021
    coupling: Coupling = Coupling.DC  # type: ignore
    min_val: float = -10.0
    max_val: float = 10.0


class NICollectorConfig(CollectorServiceConfig):
    """NI device specific config."""

    sample_rate: float = 48_000
    samples_per_read: int = 480000

    channels: list[NIChannelConfig] = field(
        default_factory=list,
    )


######## Config Example #############################
# NICollectorConfig(
#     sample_rate=48_000,
#     samples_per_read=4800,
#     channels=[
#         NIChannelConfig(
#             channel="Dev1/ai0",       # ВТ-003-Т vibration
#             iepe=True,
#             coupling=Coupling.AC,
#         ),
#         NIChannelConfig(
#             channel="Dev1/ai1",       # ВТ-003-Т temperature
#             iepe=False,
#             coupling=Coupling.DC,
#         ),
#         NIChannelConfig(
#             channel="Dev1/ai2",       # microphone
#             iepe=True,
#             coupling=Coupling.AC,
#         ),
#     ],
# )
##################################################

# class NICollectorConfig(CollectorServiceConfig):
#     """NI device specific config."""

#     channel: str = "Dev1/ai0"
#     sample_rate: float = 10_000
#     samples_per_read: int = 1000


class NICollectorData(CollectorServiceData):
    """Buffer to collect several samples at once."""

    data: Annotated[np.ndarray, SerializedNDArray]


class NIDevice:
    """Thin wrapper around NI-DAQmx hardware session."""

    def __init__(self, config: NICollectorConfig):
        self.config = config

        self.task: Task | None = None

        self.reader: AnalogSingleChannelReader | AnalogMultiChannelReader | None = None

        self.buffer: np.ndarray | None = None

    def connect(self):
        """Create and configure persistent NI task."""
        if self.task is not None:
            return
        task = Task()

        # Configure channels
        for config in self.config.channels:
            chan = task.ai_channels.add_ai_voltage_chan(
                config.channel,
                min_val=config.min_val,
                max_val=config.max_val,
            )

            if config.iepe:
                chan.ai_excit_src = ExcitationSource.INTERNAL
                chan.ai_excit_val = config.iepe_current

            chan.ai_coupling = config.coupling

        # Configure continuous acquisition
        task.timing.cfg_samp_clk_timing(
            rate=self.config.sample_rate,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=self.config.samples_per_read * 10,
        )

        # Multi-channel reader
        if len(self.config.channels) == 1:
            reader = AnalogSingleChannelReader(
                task.in_stream,
            )
        else:
            reader = AnalogMultiChannelReader(
                task.in_stream,
            )

        # [channel, sample]
        buffer = np.zeros(
            (
                len(self.config.channels),
                self.config.samples_per_read,
            ),
            dtype=np.float64,
        )

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

        self.reader.read_many_sample(  # type: ignore
            self.buffer,
            number_of_samples_per_channel=self.config.samples_per_read,
        )

        return NICollectorData(
            data=self.buffer.copy(),
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
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):  # type: ignore
        """Async context manager exit point.

        Stop the collector and cancel the publishing task.
        """
        await super().__aexit__(  # type: ignore
            exc_type,  # type: ignore
            exc_val,  # type: ignore
            exc_tb,  # type: ignore
        )

    async def start(self):
        """Open NI task and start polling."""
        if self.device.task is None:
            self.device.connect()
        try:
            await super().start()
        except Exception:
            self.device.disconnect()
            raise

    async def stop(self):
        """Stop polling and close NI task."""
        await super().stop()
        self.device.disconnect()

    def record(self) -> CollectorServiceData:
        """Simulate recording by sleeping and returning dummy data."""
        return self.device.read()
