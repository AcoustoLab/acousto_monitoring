"""Local WAV and JSON storage for audio collector messages."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated, Any
import json

from fastapi.params import Depends
from fastapi import FastAPI, Request
from fastapi.routing import APIRouter
from jsonargparse import auto_cli  # type: ignore
import numpy as np
import soundfile as sf  # type: ignore[import-untyped]
from datetime import datetime

import uvicorn

from base.audio_data import BaseAudioCollectorServiceData
from concept.storage_service import AbstractStorageService, CollectorMessage, StorageServiceConfig


logger = logging.getLogger(__file__)


def setup_logging():
    """Set up logging to file and console with rotation."""
    log_file = Path("logs/base_storage.log")
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


class LocalAudioStorageConfig(StorageServiceConfig):
    """Configuration for local audio file storage."""

    storage_id: str
    data_root: str = "data"
    storage_type: str = "local"


class LocalAudioStorageService(
    AbstractStorageService[LocalAudioStorageConfig, BaseAudioCollectorServiceData]
):
    """Store collector audio as paired WAV and JSON files."""

    def __init__(self, config: LocalAudioStorageConfig):
        super().__init__(config)

    def _connect_db(self) -> None:
        self.data_root = Path(self._config.data_root)
        self.data_root.mkdir(parents=True, exist_ok=True)
        logger.info(f"Initialized local storage at {self.data_root}")

    async def write_db(self, data: CollectorMessage[BaseAudioCollectorServiceData]) -> None:
        uid = data.get("uid")
        item = BaseAudioCollectorServiceData.model_validate(data.get("data"))
        self._write_files(uid, item)

    async def sync(self, data: BaseAudioCollectorServiceData) -> None:
        return None

    async def status(self) -> dict[str, Any]:
        count = sum(1 for _ in self.data_root.glob("**/*.wav"))
        return {
            "storage_id": self._config.storage_id,
            "storage_type": self._config.storage_type,
            "data_root": str(self.data_root),
            "file_count": count,
        }

    def _write_files(self, uid: str, item: BaseAudioCollectorServiceData) -> None:
        collected_at = datetime.fromisoformat(item.collected_at)
        rel_dir = Path(f"{collected_at:%Y}", f"{collected_at:%m}", f"{collected_at:%d}")
        target_dir = self.data_root / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        wav_rel = rel_dir / f"{collected_at:%H%M%S}_{uid}.wav"
        json_rel = rel_dir / f"{collected_at:%H%M%S}_{uid}.json"
        wav_path = self.data_root / wav_rel
        json_path = self.data_root / json_rel

        _write_wav_atomic(wav_path, item.data, item.sample_rate)
        logger.info(f"Stored audio data with {uid} at {wav_path}")

        metadata = {
            "uid": uid,
            "collected_at": item.collected_at,
            "sample_rate": item.sample_rate,
            "metadata": item.metadata,
        }
        _write_json_atomic(json_path, metadata)
        logger.info(f"Stored metadata for {uid} at {json_path}")


def _write_wav_atomic(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    """Write a WAV file through a temporary path."""
    if audio.ndim not in {1, 2}:
        raise ValueError("audio_data must be 1D mono or 2D frames/channels")
    if audio.ndim == 2 and audio.shape[1] < 1:
        raise ValueError("audio_data must have at least one channel")

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    sf.write(tmp_path, audio, sample_rate, format="WAV")  # type: ignore
    tmp_path.replace(path)


def _write_json_atomic(path: Path, metadata: dict[str, Any]) -> None:
    """Write metadata JSON through a temporary path."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


##############################################################################
#    FastAPI app
##############################################################################


def get_storage(request: Request) -> LocalAudioStorageService:
    """Get the storage service instance."""
    return request.app.state.storage


StorageDependency = Annotated[LocalAudioStorageService, Depends(get_storage)]
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
    storage: LocalAudioStorageService,  # type: ignore
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
