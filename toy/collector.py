"""Toy collector implementation."""

from typing import Annotated

from concept.collector_service import AbstractCollectorService, CollectorServiceConfig
from fastapi import FastAPI, Request, Depends
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


def get_collector(request: Request) -> ToyCollectorService:
    """Get the collector service instance."""
    return request.app.state.collector


CollectorDependency = Annotated[ToyCollectorService, Depends(get_collector)]


@app.get("/status")
async def status(collector: CollectorDependency):
    """Get collector status."""
    return await collector.status()


@app.post("/start")
async def start_collector(collector: CollectorDependency):
    """Start the collector."""
    await collector.start()
    return {"message": "Collector started"}


@app.post("/stop")
async def stop_collector(collector: CollectorDependency):
    """Stop the collector."""
    await collector.stop()
    return {"message": "Collector stopped"}


# TODO: replace `collector_config` with `config`
def main(collector_config: ToyCollectorServiceConfig, devices: list[AbstractDevice]):
    """Start the collector service."""
    collector = ToyCollectorService(config=collector_config, devices=devices)

    app.state.collector = collector
    uvicorn.run(app, port=collector_config.port)


if __name__ == "__main__":
    auto_cli(main)
