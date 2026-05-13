"""Collector service abstractions."""

from abc import ABC, abstractmethod
from pydantic import BaseModel


class CollectorServiceConfig(BaseModel):
    """Collector service configuration."""


class CollectorServiceData(BaseModel):
    """Collector service data."""


class AbstractCollectorService[
    ConfigType: CollectorServiceConfig,
    DataType: CollectorServiceData,
](ABC):
    """Abstract collector service class."""

    def __init__(
        self,
        uid: str,
        config: ConfigType,
    ):
        """Initialize the collector service.

        Parameters
        ----------
        uid : str
            Unique identifier for the collector service.
        config : CollectorServiceConfig
            Collector service configuration.
        """
        self._uid = uid
        self._config = config

    @abstractmethod
    async def start(self):
        """Start the collector service."""

    @abstractmethod
    async def stop(self):
        """Stop the collector service."""
