from concept.device import AbstractDevice, DeviceConfig, DeviceData
from typing import Any

import asyncio
import numpy as np


class ToyAcousticDeviceConfig(DeviceConfig):
    """Toy acoustic device configuration."""

    device_id: str
    sample_rate: int
    duration: int


class ToyAcousticDeviceData(DeviceData):
    """Toy acoustic device data."""

    data: list[float]


class ToyAcousticDevice(AbstractDevice):
    """Toy acoustic device class."""

    def __init__(self, config: ToyAcousticDeviceConfig):
        super().__init__(config)

    async def record(self) -> ToyAcousticDeviceData:
        """Record data."""
        length = self._config.sample_rate * self._config.duration
        data = np.random.rand(length)
        await asyncio.sleep(self._config.duration)
        return ToyAcousticDeviceData(data=list(data))

    @property
    async def status(self) -> dict[str, Any]:
        """Get device status."""
        return {"device_id": self._config.device_id, "status": "ok"}
