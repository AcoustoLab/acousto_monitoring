"""Collector service abstractions."""

from abc import ABC, abstractmethod
from pydantic import BaseModel

from enum import StrEnum
import zmq.asyncio
import threading
import asyncio
import time

from collections.abc import Callable, Awaitable
from typing import Annotated

from fastapi import Request, Depends, FastAPI
from fastapi.routing import APIRouter
from contextlib import asynccontextmanager, suppress

import logging

logger = logging.getLogger(__name__)


##############################################################################
#    Polling and publishing loops
##############################################################################


class ErrorHandlingPolicy(StrEnum):
    """Policy for handling errors during device polling."""

    IGNORE = "ignore"
    LOG = "log"
    STOP = "stop"


def device_poller_sync[T: CollectorServiceData](
    collect_fn: Callable[[], T],
    stop_event: threading.Event,
    queue: asyncio.Queue[T],
    loop: asyncio.AbstractEventLoop,
    error_policy: ErrorHandlingPolicy,
    error_retry_delay: float,
) -> bool:
    """Poll the device and put results in the queue.

    Returns False if the polling stopped due to an error and the policy is STOP, True otherwise.
    """
    logger.debug("Starting device polling loop")

    while not stop_event.is_set():
        try:
            logger.debug("Polling device...")
            data = collect_fn()
            # as the queue is async, we need to use call_soon_threadsafe to put data
            # in the queue from a different thread
            loop.call_soon_threadsafe(queue.put_nowait, data)
            logger.debug("Data put in queue")

        except Exception:
            if error_policy != ErrorHandlingPolicy.IGNORE:
                logger.error("Error polling device", exc_info=True)
            if error_policy == ErrorHandlingPolicy.STOP:
                return False
            logger.debug(f"Retrying in {error_retry_delay} seconds...")
            time.sleep(error_retry_delay)

    logger.debug("Stop event set, stopping device polling loop")
    return True


async def device_poller_async[T: CollectorServiceData](
    collect_fn: Callable[[], Awaitable[T]],
    stop_event: threading.Event,
    queue: asyncio.Queue[T],
    error_policy: ErrorHandlingPolicy,
    error_retry_delay: float,
) -> bool:
    """Poll the device and put results in the queue.

    Returns False if the polling stopped due to an error and the policy is STOP, True otherwise.
    """
    logger.debug("Starting device polling loop")

    while not stop_event.is_set():
        try:
            logger.debug("Polling device...")
            data = await collect_fn()
            await queue.put(data)
            logger.debug("Data put in queue")

        except Exception:
            if error_policy != ErrorHandlingPolicy.IGNORE:
                logger.error("Error polling device", exc_info=True)
            if error_policy == ErrorHandlingPolicy.STOP:
                return False
            logger.debug(f"Retrying in {error_retry_delay} seconds...")
            await asyncio.sleep(error_retry_delay)

    logger.debug("Stop event set, stopping device polling loop")
    return True


async def zmq_publisher[T: CollectorServiceData](
    uid: str,
    queue: asyncio.Queue[T],
    zmq_socket: zmq.asyncio.Socket,
) -> None:
    """Listen for device data and send it to zmq."""
    logger.debug("Starting zmq publisher loop")

    while True:
        try:
            data = await queue.get()
            await zmq_socket.send_json({"uid": uid, "data": data.model_dump()})  # type: ignore
            logger.debug("Data sent to zmq")
        except asyncio.CancelledError:
            # break, if task is cancled
            break
        except Exception:
            logger.error("Error sending data for device", exc_info=True)
            await asyncio.sleep(0)  # avoid busy loop if zmq is not available

    logger.debug("ZMQ publisher loop stopped")


##############################################################################
#    Collector service abstractions
##############################################################################


class CollectorServiceState(StrEnum):
    """States of the collector service."""

    RUNNING = "running"
    STOPPED = "stopped"
    STARTING = "starting"
    STOPPING = "stopping"
    ERROR = "error"


class CollectorServiceConfig(BaseModel):
    """Collector service configuration."""

    zmq_addr: str
    zmq_hwm: int = 20
    device_error_policy: ErrorHandlingPolicy = ErrorHandlingPolicy.STOP
    device_error_retry_delay_sec: float = 1.0


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
        self.__uid = uid
        self.__config = config

        # == ZMQ setup ==
        self._zmq_ctx: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None

        # == Threading and state management ==
        self.stop_event = threading.Event()
        self.stop_event.set()

        self.state_lock = asyncio.Lock()  # locks the state of the collector (running/stopped)
        self.state: CollectorServiceState = CollectorServiceState.STOPPED

        self.device_queue = asyncio.Queue[DataType]()
        self.publishing_task: None | asyncio.Task[None] = None
        self.device_pooling_task: None | asyncio.Task[bool] = None

    async def __aenter__(self):
        """Async context manager entry point.

        Start a publishing task that listens for device data and sends it to zmq.
        """
        self._zmq_ctx = zmq.asyncio.Context()
        self._socket = self._zmq_ctx.socket(zmq.PUB)
        # Newer message will be dropped when the queue is full, instead of blocking the publisher
        self._socket.setsockopt(zmq.SNDHWM, self.config.zmq_hwm)
        self._socket.bind(self.config.zmq_addr)

        self.publishing_task = asyncio.create_task(
            zmq_publisher(
                uid=self.uid,
                queue=self.device_queue,
                zmq_socket=self._socket,
            )
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):  # type: ignore
        """Async context manager exit point.

        Stop the collector and cancel the publishing task.
        """
        await self.stop()
        if self.publishing_task is not None:
            self.publishing_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.publishing_task
            self.publishing_task = None

        if self._socket is not None:
            self._socket.close()
            self._socket = None

        if self._zmq_ctx is not None:
            self._zmq_ctx.term()
            self._zmq_ctx = None

    @property
    def uid(self) -> str:
        """Get the unique identifier of the collector service."""
        return self.__uid

    @property
    def config(self) -> ConfigType:
        """Get the configuration of the collector service."""
        return self.__config

    async def status(self) -> dict[str, str]:
        """Get collector status. User can add more information here if needed."""
        return {"state": self.state}

    @abstractmethod
    def _start_device_pooling_task(self) -> asyncio.Task[bool]: ...

    async def start(self):
        """Start the device polling."""

        def handle_device_error(task: asyncio.Task[bool]):
            result = task.result()
            if result is False:
                # the polling stopped due to an error, set state to error
                self.state = CollectorServiceState.ERROR
                logger.info("Collector stopped due to device polling error")

        async with self.state_lock:
            if self.state == CollectorServiceState.RUNNING:
                return

            try:
                self.state = CollectorServiceState.STARTING
                self.stop_event.clear()

                self.device_pooling_task = self._start_device_pooling_task()
                self.device_pooling_task.add_done_callback(handle_device_error)

            except Exception as e:
                logger.error("Error starting collector", exc_info=True)
                self.state = CollectorServiceState.STOPPED
                raise e

            self.state = CollectorServiceState.RUNNING
            logger.info("Collector started")

    async def stop(self):
        """Stop the device polling."""
        async with self.state_lock:
            self.state = CollectorServiceState.STOPPING
            self.stop_event.set()

            # await pulling task to finish
            if self.device_pooling_task is not None:
                await self.device_pooling_task

            self.device_pooling_task = None
            self.state = CollectorServiceState.STOPPED
            logger.info("Collector stopped")


class CollectorService[
    ConfigType: CollectorServiceConfig,
    DataType: CollectorServiceData,
](AbstractCollectorService[ConfigType, DataType], ABC):
    """Abstract collector service class for blocking device calls."""

    @abstractmethod
    def record(self) -> DataType: ...

    def _start_device_pooling_task(self) -> asyncio.Task[bool]:
        loop = asyncio.get_running_loop()
        return loop.create_task(
            asyncio.to_thread(
                device_poller_sync,
                collect_fn=self.record,
                stop_event=self.stop_event,
                queue=self.device_queue,
                loop=loop,
                error_policy=self.config.device_error_policy,
                error_retry_delay=self.config.device_error_retry_delay_sec,
            )
        )


class AsyncCollectorService[
    ConfigType: CollectorServiceConfig,
    DataType: CollectorServiceData,
](AbstractCollectorService[ConfigType, DataType], ABC):
    """Abstract collector service class for async device calls."""

    @abstractmethod
    async def record(self) -> DataType: ...

    def _start_device_pooling_task(self):
        return asyncio.create_task(
            device_poller_async(
                collect_fn=self.record,
                stop_event=self.stop_event,
                queue=self.device_queue,
                error_policy=self.config.device_error_policy,
                error_retry_delay=self.config.device_error_retry_delay_sec,
            )
        )


##############################################################################
#    FastAPI app
##############################################################################


def _collector_service_app_lifespan(
    collector: AbstractCollectorService[CollectorServiceConfig, CollectorServiceData],
):
    """
    Create a lifespan function for the FastAPI app that manages the collector service lifecycle.

    The collector service will be started when the app starts and stopped when the app shuts down
    using the `__aenter__` and `__aexit__` methods of the collector.
    """

    @asynccontextmanager
    async def lifespan(
        app: FastAPI,
    ):
        async with collector:
            # set the collector instance in the app state
            # so that it can be accessed in the endpoints
            app.state.collector = collector
            yield

    return lifespan


def _collector_dependency(
    request: Request,
) -> AbstractCollectorService[CollectorServiceConfig, CollectorServiceData]:
    """Get the collector service instance."""
    # the collector instance is set in the app state in the lifespan function
    return request.app.state.collector


CollectorDependency = Annotated[
    AbstractCollectorService[CollectorServiceConfig, CollectorServiceData],
    Depends(_collector_dependency),
]
router = APIRouter()


@router.get("/status")
async def status(collector: CollectorDependency) -> dict[str, str]:
    """Get collector status."""
    return await collector.status()


@router.post("/start")
async def start(collector: CollectorDependency):
    """Start the collector."""
    await collector.start()


@router.post("/stop")
async def stop(collector: CollectorDependency):
    """Stop the collector."""
    await collector.stop()


def get_app(
    collector: AbstractCollectorService[CollectorServiceConfig, CollectorServiceData],
) -> FastAPI:
    """Create the FastAPI app with the collector service."""
    lifespan = _collector_service_app_lifespan(collector)

    app = FastAPI(title="Collector Service", lifespan=lifespan)
    app.include_router(router, prefix="/api")

    # add just a simple root endpoint to check if the service is alive
    app.get("/")(lambda: "alive")

    return app
