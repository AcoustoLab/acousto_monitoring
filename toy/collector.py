"""Toy collector implementation."""

from concept.collector_service import AbstractCollectorService, CollectorServiceConfig
from fastapi import FastAPI, Request
from concept.device import AbstractDevice
import uvicorn
from jsonargparse import auto_cli  # type: ignore


class ToyCollectorServiceConfig(CollectorServiceConfig):
    """Toy collector configuration."""

    port: int


class ToyCollectorService(AbstractCollectorService):
    """Toy collector implementation."""

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
async def status(request: Request):
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


def main(collector_config: ToyCollectorServiceConfig, devices: list[AbstractDevice]):
    """Start the collector service."""
    collector = ToyCollectorService(config=collector_config, devices=devices)

    app.state.collector = collector
    uvicorn.run(app)


if __name__ == "__main__":
    auto_cli(main)
