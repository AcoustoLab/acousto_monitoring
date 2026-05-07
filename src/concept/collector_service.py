"""Collector service abstractions."""

from abc import ABC, abstractmethod

import zmq.asyncio

from pydantic import BaseModel

from concept.device import AbstractDevice


class CollectorServiceConfig(BaseModel):
    """Collector service configuration."""


class AbstractCollectorService(ABC):
    """Abstract collector service class."""

    def __init__(self, config: CollectorServiceConfig, devices: list[AbstractDevice]):
        self._config = config
        self._devices = devices
        self._zmq_ctx = zmq.asyncio.Context()
        self._push_socket = None

    @abstractmethod
    async def start(self):
        """Start the collector service."""

    @abstractmethod
    async def stop(self):
        """Stop the collector service."""