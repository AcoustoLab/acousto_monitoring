"""Device abstractions."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel
import numpy as np


class DeviceConfig(BaseModel):
    """Device configuration."""


class AbstractDevice(ABC):
    """Abstract device class."""

    def __init__(self, config: DeviceConfig):
        self._config = config

    @abstractmethod
    async def record(self) -> np.ndarray:
        """Record data."""

    @property
    @abstractmethod
    async def status(self) -> dict[str, Any]:
        """Get device status."""
