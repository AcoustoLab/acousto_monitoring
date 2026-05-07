from concept.device import AbstractDevice, DeviceConfig
from typing import Any

import asyncio
import numpy as np


class ToyAcousticDeviceConfig(DeviceConfig):
    """Toy acoustic device configuration."""

    device_id: str
    sample_rate: int
    duration: int


class ToyAcousticDevice(AbstractDevice):
    """Toy acoustic device class."""

    def __init__(self, config: ToyAcousticDeviceConfig):
        super().__init__(config)

    async def record(self) -> np.ndarray:
        """Record data."""
        while True:
            length = self._config.sample_rate * self._config.duration
            data = np.random.rand(length)
            await asyncio.sleep(self._config.duration)
            yield data

    @property
    async def status(self) -> dict[str, Any]:
        """Get device status."""
        return {"device_id": self._config.device_id, "status": "ok"}
