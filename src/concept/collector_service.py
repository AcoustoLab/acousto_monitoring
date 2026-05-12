"""Collector service abstractions."""

from abc import ABC, abstractmethod
from pydantic import BaseModel
from concept.device import AbstractDevice
from collections.abc import Mapping
from typing import TypeVar


class CollectorServiceConfig(BaseModel):
    """Collector service configuration."""


ConfigType = TypeVar("ConfigType", bound=CollectorServiceConfig)


class AbstractCollectorService[ConfigType](ABC):
    """Abstract collector service class."""

    def __init__(self, config: ConfigType, devices: Mapping[str, AbstractDevice]):
        """Initialize the collector service.

        Parameters
        ----------
        config : CollectorServiceConfig
            Collector service configuration.
        devices : Mapping[str, AbstractDevice]
            Devices to collect data from.
        """
        self._config = config
        self._devices = dict(devices)

    @abstractmethod
    async def start(self):
        """Start the collector service."""

    @abstractmethod
    async def stop(self):
        """Stop the collector service."""
