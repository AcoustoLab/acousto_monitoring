"""Toy collector implementation."""

from concept.collector_service import AbstractCollectorService
from concept.collector_service import CollectorServiceConfig, CollectorServiceData

from typing import Annotated
from collections.abc import Callable, Awaitable

import zmq.asyncio
import asyncio
import threading

from fastapi import Request, Depends, FastAPI
from fastapi.routing import APIRouter
import uvicorn

from jsonargparse import auto_cli  # type: ignore

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import inspect
import time
import numpy as np
from pydantic_serializers import SerializedNDArray


logger = logging.getLogger(__file__)


def _put_nowait_with_drop[T: CollectorServiceData](
    queue: asyncio.Queue[T],
    uid: str,
    data: T,
) -> None:
    """Put data in the queue, dropping old data if the queue is full."""
    try:
        queue.put_nowait(data)
    except asyncio.QueueFull:
        logger.warning(
            f"Device {uid} queue full, dropping data",
        )
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                queue.put_nowait(data)
                break


def device_poller_sync[T: CollectorServiceData](
    uid: str,
    collect_fn: Callable[[], T],
    stop_event: threading.Event,
    queue: asyncio.Queue[T],
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Poll the device and put results in the queue."""
    while not stop_event.is_set():
        try:
            data = collect_fn()  # blocking device call
            loop.call_soon_threadsafe(_put_nowait_with_drop, queue, uid, data)

        except Exception:
            logger.error(f"Error polling device {uid}", exc_info=True)


async def device_poller_async[T: CollectorServiceData](
    uid: str,
    collect_fn: Callable[[], Awaitable[T]],
    stop_event: threading.Event,
    queue: asyncio.Queue[T],
) -> None:
    """Poll the device and put results in the queue."""
    while not stop_event.is_set():
        try:
            data = await collect_fn()
            _put_nowait_with_drop(queue, uid, data)
        except asyncio.CancelledError:
            # break, if task is cancled
            break
        except Exception:
            logger.error(f"Error polling device {uid}", exc_info=True)


async def device_listener_asyncio[T: CollectorServiceData](
    uid: str,
    queue: asyncio.Queue[T],
    zmq_socket: zmq.asyncio.Socket,
) -> None:
    """Listen for device data and send it to zmq."""
    while True:
        try:
            data = await queue.get()
            print("Got data from device", uid)
            await zmq_socket.send_json({"device": uid, "data": data.model_dump()})  # type: ignore
        except Exception:
            logger.error(f"Error sending data for device {uid}", exc_info=True)


class ToyCollectorServiceConfig(CollectorServiceConfig):
    """Toy collector configuration."""

    zmq_addr: str
    sample_rate: int
    duration: int


class ToyCollectorServiceData(CollectorServiceData):
    """Toy acoustic device data."""

    data: Annotated[np.ndarray, SerializedNDArray]


class ToyCollectorService(
    AbstractCollectorService[ToyCollectorServiceConfig, ToyCollectorServiceData]
):
    """Toy collector implementation."""

    def __init__(
        self,
        uid: str,
        config: ToyCollectorServiceConfig,
    ):
        """Initialize the toy collector service."""
        super().__init__(uid=uid, config=config)

        self._zmq_ctx = zmq.asyncio.Context()
        self._socket = self._zmq_ctx.socket(zmq.PUB)

        self._socket.bind(self._config.zmq_addr)

        self.stop_event = threading.Event()
        self.stop_event.set()

        self.state_lock = asyncio.Lock()

        self.device_queue = asyncio.Queue[ToyCollectorServiceData](20)
        # start infinite publishing loop
        self.publishing_task = asyncio.create_task(
            device_listener_asyncio(
                uid=self._uid,
                queue=self.device_queue,
                zmq_socket=self._socket,
            )
        )
        self.device_pooling_task: None | asyncio.Task[None] = None

    def record(self) -> ToyCollectorServiceData:
        length = self._config.sample_rate * self._config.duration
        data = np.random.rand(length)
        time.sleep(self._config.duration)
        return ToyCollectorServiceData(data=data)

    async def start(self):
        async with self.state_lock:
            if not self.stop_event.is_set():
                # Do not start, if running
                return

            loop = asyncio.get_running_loop()

            if not inspect.iscoroutinefunction(self.record):
                # Create a thread and start polling
                self.device_pooling_task = asyncio.create_task(
                    asyncio.to_thread(
                        device_poller_sync,
                        self._uid,
                        self.record,
                        self.stop_event,
                        self.device_queue,
                        loop,
                    )
                )
            else:
                # Start polling
                self.device_pooling_task = asyncio.create_task(
                    device_poller_async(
                        self._uid,
                        self.record,
                        self.stop_event,
                        self.device_queue,
                    )
                )

            self.stop_event.clear()
            logger.info("Collector started")

    async def stop(self):
        async with self.state_lock:
            self.stop_event.set()

            # cancel the pooling task and await its finish
            pooling_task = self.device_pooling_task
            if pooling_task is not None and not pooling_task.done():
                pooling_task.cancel()
                await asyncio.wait([pooling_task], return_when=asyncio.ALL_COMPLETED)

            self.device_pooling_task = None
            logger.info("Collector stopped")

    async def status(self) -> dict[str, str]:
        """Get collector status."""
        return {"status": "stopped" if self.stop_event.is_set() else "running"}


##############################################################################
#    FastAPI app
##############################################################################


def get_collector(request: Request) -> ToyCollectorService:
    """Get the collector service instance."""
    return request.app.state.collector


CollectorDependency = Annotated[ToyCollectorService, Depends(get_collector)]
router = APIRouter()


@router.get("/status")
async def status(collector: CollectorDependency):
    """Get collector status."""
    return await collector.status()


@router.post("/start")
async def start_collector(collector: CollectorDependency):
    """Start the collector."""
    await collector.start()
    return {"message": "Collector started"}


@router.post("/stop")
async def stop_collector(collector: CollectorDependency):
    """Stop the collector."""
    await collector.stop()
    return {"message": "Collector stopped"}


##############################################################################
#    Main function
##############################################################################


def main(
    api_port: int,
    collector: AbstractCollectorService,  # type: ignore
):
    """Start the collector service."""
    # Create the FastAPI app and include the api router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.get("/")(lambda: "alive")
    app.state.collector = collector

    # setup logging
    log_file = Path().cwd() / "logs" / "collector.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s (%(name)s) [%(levelname)s] %(message)s")

    handler = RotatingFileHandler(log_file, maxBytes=1 * 1024 * 1024, backupCount=5)
    handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(handler)
    logger.addHandler(console_handler)
    logger.setLevel(logging.INFO)

    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.addHandler(handler)
    uvicorn_logger.addHandler(console_handler)
    uvicorn_logger.setLevel(logging.INFO)

    # Start the FastAPI app
    uvicorn.run(app, port=api_port, log_config=None)


if __name__ == "__main__":
    auto_cli(main)
