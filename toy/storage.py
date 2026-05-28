"""Toy storage service implementation."""

from typing import Annotated, Any

import asyncio
import os
import sqlite3
import json
import time

from concept.storage_service import AbstractStorageService, CollectorMessage, StorageServiceConfig
from fastapi import Depends, FastAPI, Request
from fastapi.routing import APIRouter
from jsonargparse import auto_cli  # type: ignore
from toy.collector import ToyCollectorServiceData
import uvicorn

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


logger = logging.getLogger(__file__)


def setup_logging():
    """Set up logging to file and console with rotation."""
    log_file = Path("logs/storage.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s (%(name)s) [%(levelname)s] %(message)s",
        handlers=[
            RotatingFileHandler(log_file, maxBytes=1024 * 1024, backupCount=5),
            logging.StreamHandler(),
        ],
        force=True,
    )


class ToyStorageConfig(StorageServiceConfig):
    """Toy storage configuration."""

    storage_id: str
    storage_type: str
    db_path: str
    zmq_sub_addrs: list[str]


class ToyStorageService(AbstractStorageService[ToyStorageConfig, ToyCollectorServiceData]):
    """Toy storage service implementation with simple SQLite database."""

    def __init__(self, config: ToyStorageConfig):
        super().__init__(config)

    def _connect_db(self):
        """Connect to the SQLite database."""
        db_dir = os.path.dirname(self._config.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self.db = sqlite3.connect(self._config.db_path, check_same_thread=False)
        cursor = self.db.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS device_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_name TEXT,
                timestamp REAL,
                data TEXT
            )
            """
        )
        self.db.commit()

    async def write_db(self, data: CollectorMessage[ToyCollectorServiceData]) -> None:
        """Write a message from the collector to the SQLite database.

        Expected message shape: {"device": <uid>, "data": <model_dump dict>}.
        """

        def _write():
            assert self.db is not None
            device = data.get("device")
            payload = data.get("data")
            ts = time.time()
            payload = ToyCollectorServiceData.model_validate(payload).model_dump()
            payload_json = json.dumps(payload, separators=(",", ":"))

            cursor = self.db.cursor()
            cursor.execute(
                """
                INSERT INTO device_data (device_name, timestamp, data)
                VALUES (?, ?, ?)
                """,
                (device, ts, payload_json),
            )
            self.db.commit()

            print(f"Stored data from device {device}")

        await asyncio.to_thread(_write)

    async def sync(self, data: ToyCollectorServiceData) -> None:
        """Sync data."""
        pass

    async def status(self) -> dict[str, Any]:
        """Get database status."""

        def _status():
            assert self.db is not None
            cursor = self.db.cursor()
            cursor.execute("SELECT COUNT(*) FROM device_data")
            count = cursor.fetchone()[0]
            return {
                "storage_id": self._config.storage_id,
                "storage_type": self._config.storage_type,
                "db_path": self._config.db_path,
                "data_count": count,
            }

        return await asyncio.to_thread(_status)


##############################################################################
#    FastAPI app
##############################################################################


def get_storage(request: Request) -> ToyStorageService:
    """Get the storage service instance."""
    return request.app.state.storage


StorageDependency = Annotated[ToyStorageService, Depends(get_storage)]
router = APIRouter()


@router.get("/status")
async def status(storage: StorageDependency):
    """Get storage status."""
    return await storage.status()


@router.post("/start")
async def start_storage(storage: StorageDependency):
    """Start storage collection."""
    await storage.start()
    logger.info("Storage collection started")
    return {"message": "Storage started"}


@router.post("/stop")
async def stop_storage(storage: StorageDependency):
    """Stop storage collection."""
    await storage.stop()
    logger.info("Storage collection stopped")
    return {"message": "Storage stopped"}


##############################################################################
#    Main function
##############################################################################


def main(
    api_port: int,
    storage: AbstractStorageService,  # type: ignore
):
    """Main function to run the toy storage service."""
    setup_logging()

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.get("/")(lambda: "alive")
    app.state.storage = storage

    logger.info("Starting storage API on port %s", api_port)
    uvicorn.run(app, port=api_port, log_config=None)


if __name__ == "__main__":
    auto_cli(main)
