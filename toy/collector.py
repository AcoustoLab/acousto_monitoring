"""Toy collector implementation."""

from concept.collector_service import AbstractCollectorService, CollectorServiceConfig
from concept.device import AbstractDevice, DeviceData
from typing import Annotated, Any
from collections.abc import Mapping, Callable, Awaitable
import zmq.asyncio
import asyncio
import threading
from fastapi import Request, Depends, FastAPI
from fastapi.routing import APIRouter
import uvicorn
from jsonargparse import auto_cli  # type: ignore
import inspect
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

logger = logging.getLogger(__file__)


def _put_nowait_with_drop(
    device_queue: asyncio.Queue[DeviceData],
    device_name: str,
    data: DeviceData,
) -> None:
    """Put data in the queue, dropping old data if the queue is full."""
    try:
        device_queue.put_nowait(data)
    except asyncio.QueueFull:
        logger.warning(
            f"Device {device_name} queue full, dropping data",
        )
        while True:
            try:
                device_queue.get_nowait()
            except asyncio.QueueEmpty:
                device_queue.put_nowait(data)
                break


def device_poller_sync(
    device_name: str,
    collect_fn: Callable[[], DeviceData],
    stop_event: threading.Event,
    device_queue: asyncio.Queue[DeviceData],
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Poll the device and put results in the queue."""
    while not stop_event.is_set():
        try:
            data = collect_fn()  # blocking device call

            loop.call_soon_threadsafe(_put_nowait_with_drop, device_queue, device_name, data)

        except Exception:
            logger.error(f"Error polling device {device_name}", exc_info=True)


async def device_poller_async(
    device_name: str,
    collect_fn: Callable[[], Awaitable[DeviceData]],
    stop_event: threading.Event,
    device_queue: asyncio.Queue[DeviceData],
) -> None:
    """Poll the device and put results in the queue."""
    while not stop_event.is_set():
        try:
            data = await collect_fn()
            _put_nowait_with_drop(device_queue, device_name, data)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.error(f"Error polling device {device_name}", exc_info=True)


async def device_listener_asyncio(
    device_name: str,
    device_queue: asyncio.Queue[DeviceData],
    zmq_socket: zmq.asyncio.Socket,
) -> None:
    """Listen for device data and send it to zmq."""
    while True:
        try:
            data = await device_queue.get()
            print("Got data from device", device_name)
            await zmq_socket.send_json({"device": device_name, "data": data.model_dump()})  # type: ignore
        except Exception:
            logger.error(f"Error sending data for device {device_name}", exc_info=True)


class ToyCollectorServiceConfig(CollectorServiceConfig):
    """Toy collector configuration."""

    api_port: int
    zmq_addr: str


class ToyCollectorService(AbstractCollectorService[ToyCollectorServiceConfig]):
    """Toy collector implementation."""

    def __init__(
        self,
        config: ToyCollectorServiceConfig,
        devices: Mapping[str, AbstractDevice[Any, Any]],
    ):
        """Initialize the toy collector service."""
        super().__init__(config=config, devices=devices)

        self._zmq_ctx = zmq.asyncio.Context()
        self._socket = self._zmq_ctx.socket(zmq.PUB)

        self._socket.bind(self._config.zmq_addr)

        self.stop_event = threading.Event()
        self.stop_event.set()

        self.state_lock = asyncio.Lock()

        self.device_queues = {
            device_name: asyncio.Queue[DeviceData]() for device_name in self._devices
        }
        self.publishing_tasks: dict[str, asyncio.Task[None]] = {}
        self.device_pooling_tasks: set[asyncio.Task[None]] = set()

    async def check_publishing_tasks(self):
        # Check if publishing tasks are running, if not start them
        for device_name, device_queue in self.device_queues.items():
            if device_name in self.publishing_tasks:
                continue

            task = asyncio.create_task(
                device_listener_asyncio(
                    device_name=device_name,
                    device_queue=device_queue,
                    zmq_socket=self._socket,
                )
            )

            self.publishing_tasks[device_name] = task

    async def start(self):
        async with self.state_lock:
            if not self.stop_event.is_set():
                return

            await self.check_publishing_tasks()

            # For each device create a thread and start polling
            # For each device create a task that listens queue and sends data to zmq
            loop = asyncio.get_running_loop()
            for device_name, device in self._devices.items():
                if not inspect.iscoroutinefunction(device.record):
                    task = asyncio.create_task(
                        asyncio.to_thread(
                            device_poller_sync,
                            device_name,
                            device.record,
                            self.stop_event,
                            self.device_queues[device_name],
                            loop,
                        )
                    )
                else:
                    task = asyncio.create_task(
                        device_poller_async(
                            device_name,
                            device.record,
                            self.stop_event,
                            self.device_queues[device_name],
                        )
                    )
                self.device_pooling_tasks.add(task)

            self.stop_event.clear()
            logger.info("Collector started")

    async def stop(self):
        async with self.state_lock:
            self.stop_event.set()

            for task in self.device_pooling_tasks:
                task.cancel()

            await asyncio.gather(*self.device_pooling_tasks, return_exceptions=True)
            self.device_pooling_tasks.clear()

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
    service_config: ToyCollectorServiceConfig,
    devices: Mapping[str, AbstractDevice],  # type: ignore
):
    """Start the collector service."""
    # Create the service instance
    collector = ToyCollectorService(config=service_config, devices=devices)  # type: ignore

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
    uvicorn.run(app, port=service_config.api_port, log_config=None)


if __name__ == "__main__":
    auto_cli(main)
