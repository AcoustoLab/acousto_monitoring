"""Device abstractions."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class DeviceConfig(BaseModel):
    """Device configuration."""


class DeviceData(BaseModel):
    """Device data."""


class AbstractDevice[DeviceConfigT: DeviceConfig, DeviceDataT: DeviceData](ABC):
    """Abstract device class."""

    def __init__(self, config: DeviceConfigT):
        self._config = config

    @abstractmethod
    def record(self) -> DeviceDataT:
        """Record data."""

    @property
    @abstractmethod
    def status(self) -> dict[str, Any]:
        """Get device status."""
