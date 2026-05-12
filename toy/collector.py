"""Toy collector implementation."""

from concept.collector_service import AbstractCollectorService, CollectorServiceConfig
from concept.device import AbstractDevice, DeviceData
from typing import Annotated
from collections.abc import Mapping, Callable, Awaitable
import zmq.asyncio
import asyncio
import threading
from fastapi import Request, Depends, FastAPI
from fastapi.routing import APIRouter
import uvicorn
from jsonargparse import auto_cli  # type: ignore
import logging


logger = logging.getLogger(__file__)


def _put_nowait_with_drop(
    device_queue: asyncio.Queue[DeviceData], device_name: str, data: DeviceData
) -> None:

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


def device_poller_threading(
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

        except Exception:
            logger.error(f"Error polling device {device_name}", exc_info=True)


async def device_listener_asyncio(
    device_name: str,
    device_queue: asyncio.Queue[DeviceData],
    zmq_socket: zmq.asyncio.Socket,
) -> None:
    """Listen for device data and send it to zmq."""
    try:
        data = await device_queue.get()
        await zmq_socket.send_json({"device": device_name, "data": data})
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
        devices: Mapping[str, AbstractDevice],
    ):
        """Initialize the toy collector service."""
        super().__init__(config=config, devices=devices)

        self._zmq_ctx = zmq.asyncio.Context()
        self._socket = self._zmq_ctx.socket(zmq.PUB)

        self._socket.bind(self._config.zmq_addr)

        self.stop_event = threading.Event()
        self.stop_event.set()

        self.device_queues = {
            device_name: asyncio.Queue[DeviceData]() for device_name in self._devices
        }
        self.publishing_tasks: dict[str, asyncio.Task[None]] = {}
        self.device_pooling_tasks: list[asyncio.Task[None]] = []

    async def check_publishing_tasks(self):

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
        if not self.stop_event.is_set():
            return

        await self.check_publishing_tasks()

        self.stop_event.clear()
        # For each device create a thread and start polling
        # For each device create a task that listens queue and sends data to zmq
        loop = asyncio.get_running_loop()
        for device_name, device in self._devices.items():
            if False:
                task = asyncio.create_task(
                    asyncio.to_thread(
                        device_poller_threading,
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
            self.device_pooling_tasks.append(task)
        print("Collector started")

    async def stop(self):
        self.stop_event.set()
        print("Collector stopped")

    async def status(self) -> dict[str, str]:
        """Get collector status."""
        return {"status": "running"}


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
    devices: Mapping[str, AbstractDevice],
):
    """Start the collector service."""
    # Create the service instance
    collector = ToyCollectorService(config=service_config, devices=devices)

    # Create the FastAPI app and include the api router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.get("/")(lambda: "alive")
    app.state.collector = collector

    # Start the FastAPI app
    uvicorn.run(app, port=service_config.api_port)


if __name__ == "__main__":
    auto_cli(main)
