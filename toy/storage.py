"""Toy storage service implementation."""

from typing import Annotated, Any

import asyncio
import os
import sqlite3
import json
import time

from concept.storage_service import AbstractStorageService, StorageServiceConfig
from fastapi import Depends, FastAPI, Request
from fastapi.routing import APIRouter
from jsonargparse import auto_cli  # type: ignore
from collector import ToyCollectorServiceData
import uvicorn


class ToyStorageConfig(StorageServiceConfig):
    """Toy storage configuration."""

    storage_id: str
    storage_type: str
    db_path: str
    zmq_sub_addrs: list[str]


class ToyStorageService(AbstractStorageService[ToyStorageConfig]):
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

    async def write_db(self, data: dict[str, Any]):
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

        await asyncio.to_thread(_write)

    async def sync(self, data: dict[str, Any]):
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
    return {"message": "Storage started"}


@router.post("/stop")
async def stop_storage(storage: StorageDependency):
    """Stop storage collection."""
    await storage.stop()
    return {"message": "Storage stopped"}


##############################################################################
#    Main function
##############################################################################


def main(
    api_port: int,
    storage: AbstractStorageService,  # type: ignore
):
    """Main function to run the toy storage service."""
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.get("/")(lambda: "alive")
    app.state.storage = storage

    uvicorn.run(app, port=api_port)


if __name__ == "__main__":
    auto_cli(main)
