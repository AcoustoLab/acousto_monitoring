"""Toy collector implementation."""

from concept.collector import Collector
from concept.collector import CollectorConfig, SetupConfig
from fastapi import FastAPI, Request
import uvicorn
from concept.device import AbstractDevice
from collections.abc import Iterable
from jsonargparse import auto_cli


class ToyCollector(Collector):
    """Toy collector implementation."""

    def __init__(
        self, config: CollectorConfig, setup_config: SetupConfig, devices: Iterable[AbstractDevice]
    ):
        super().__init__(config, setup_config)
        self.devices = devices

    async def start(self):
        """Start the collector."""
        print("Collector started")

    async def stop(self):
        """Stop the collector."""
        print("Collector stopped")

    async def status(self) -> dict[str, str]:
        """Get collector status."""
        return {"status": "running"}


app = FastAPI()


@app.get("/status")
async def get_status(request: Request):
    """Get collector status."""
    return await request.app.state.collector.status()


@app.post("/start")
async def start_collector(request: Request):
    """Start the collector."""
    await request.app.state.collector.start()
    return {"message": "Collector started"}


@app.post("/stop")
async def stop_collector(request: Request):
    """Stop the collector."""
    await request.app.state.collector.stop()
    return {"message": "Collector stopped"}


def main(devices: Iterable[AbstractDevice]):
    """Start the collector service."""
    collector_config = CollectorConfig()
    setup_config = SetupConfig()
    collector = ToyCollector(collector_config, setup_config, devices)

    app.state.collector = collector
    uvicorn.run(app)


if __name__ == "__main__":
    auto_cli(main)
