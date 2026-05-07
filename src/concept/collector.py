"""Collector module."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class CollectorConfig(BaseModel):
    """Collector configuration."""


class SetupConfig(BaseModel):
    """Setup configuration."""


class Collector(ABC):
    """Collector class."""

    def __init__(self, config: CollectorConfig, setup_config: SetupConfig):
        self._config = config
        self._setup_config = setup_config

    @abstractmethod
    async def start(self):
        """Start the collector."""

    @abstractmethod
    async def stop(self):
        """Stop the collector."""

    @abstractmethod
    async def status(self) -> dict[str, Any]:
        """Get collector status."""
