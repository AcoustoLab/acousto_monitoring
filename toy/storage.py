"""Toy storage service implementation."""

from typing import Any

import asyncio
import os
import sqlite3

from concept.storage_service import AbstractStorageService, StorageServiceConfig

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
        """Write data to the SQLite database."""
        def _write():
            assert self.db is not None
            cursor = self.db.cursor()
            cursor.execute(
                """
                INSERT INTO device_data (device_name, timestamp, data)
                VALUES (?, ?, ?)
                """,
                (data["device_name"], data["timestamp"], str(data["data"])),
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


def main(
    config: ToyStorageConfig,
):
    """Main function to run the toy storage service."""
    storage_service = ToyStorageService(config)

    async def _run():
        status = await storage_service.status()
        print(status)
        await storage_service.start()
        await storage_service.stop()

    asyncio.run(_run())


if __name__ == "__main__":
    import yaml
    with open("toy/storage_config.yaml") as f:
        config_dict = yaml.safe_load(f)

    config = ToyStorageConfig(**config_dict["storage_config"])
    main(config)
