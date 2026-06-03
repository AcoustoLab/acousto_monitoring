"""Sync local files to object storage on a timer or file-count trigger."""

import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated, Any

from jsonargparse import auto_cli  # type: ignore
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import uvicorn

from src.concept.s3_sync_service import S3StorageClient, S3SyncConfigBase, S3SyncService
from fastapi import Depends, FastAPI, Request
from fastapi.routing import APIRouter

_MARKER_SUFFIX = ".uploaded"

logger = logging.getLogger(__name__)


def setup_logging():  # pragma: no cover
    """Set up logging to file and console with rotation."""
    log_file = Path("logs/s3_sync.log")
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


class S3SyncConfig(S3SyncConfigBase):
    """Configuration for S3SyncService."""

    data_root: str
    upload_every_n_files: int = 60
    upload_every_seconds: int = 600
    delete_after_upload: bool = False


class S3SyncServiceBase(S3SyncService):
    """Watches a local directory and syncs new files to object storage."""

    def __init__(self, config: S3SyncConfig, client: S3StorageClient) -> None:
        self._config = config
        self._client = client
        self._data_root = Path(config.data_root)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("S3SyncService started, watching %s", self._data_root)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        logger.info("S3SyncService stopped")

    async def sync_once(self) -> None:
        """Upload all pending files (no .uploaded marker) to object storage."""
        pending = self._pending_files()
        if not pending:
            return

        logger.info("Syncing %d file(s) to S3", len(pending))
        for local_path in pending:
            key = local_path.relative_to(self._data_root).as_posix()
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self._upload_with_retry, local_path, key
                )
                local_path.with_suffix(local_path.suffix + _MARKER_SUFFIX).touch()
                if self._config.delete_after_upload:
                    local_path.unlink()
                    logger.info("Deleted local file %s after upload", local_path)
            except Exception:
                logger.exception("Failed to upload %s, will retry next cycle", local_path)

    async def status(self) -> dict[str, Any]:
        pending = self._pending_files()
        uploaded = list(self._data_root.glob(f"**/*{_MARKER_SUFFIX}"))
        return {
            "data_root": str(self._data_root),
            "pending": len(pending),
            "uploaded": len(uploaded),
            "running": self._task is not None and not self._task.done(),
        }

    async def _loop(self) -> None:
        elapsed = 0.0
        interval = 1.0
        while True:
            await asyncio.sleep(interval)
            elapsed += interval
            pending_count = len(self._pending_files())
            time_trigger = elapsed >= self._config.upload_every_seconds
            count_trigger = pending_count >= self._config.upload_every_n_files
            if time_trigger or count_trigger:
                await self.sync_once()
                elapsed = 0.0

    def _pending_files(self) -> list[Path]:
        """All .wav and .json files that don't have a corresponding .uploaded marker."""
        return [
            p for p in self._data_root.glob("**/*")
            if p.is_file()
            and p.suffix in {".wav", ".json"}
            and not p.with_suffix(p.suffix + _MARKER_SUFFIX).exists()
        ]

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _upload_with_retry(self, local_path: Path, key: str) -> None:
        self._client.upload(local_path, key)


##############################################################################
#    FastAPI app
##############################################################################


def get_s3_sync_service(request: Request) -> S3SyncServiceBase:  # pragma: no cover
    """Get the S3SyncService instance."""
    return request.app.state.s3_sync_service


S3_SyncServiceDependency = Annotated[S3SyncServiceBase, Depends(get_s3_sync_service)]
router = APIRouter()


@router.get("/status")
async def status(s3_sync_service: S3_SyncServiceDependency):
    """Get S3 sync service status."""
    return await s3_sync_service.status()


@router.post("/start")
async def start_s3_sync_service(s3_sync_service: S3_SyncServiceDependency):
    """Start S3 sync service."""
    await s3_sync_service.start()
    logger.info("S3 sync service started")
    return {"message": "S3 sync service started"}


@router.post("/stop")
async def stop_s3_sync_service(s3_sync_service: S3_SyncServiceDependency):
    """Stop S3 sync service."""
    await s3_sync_service.stop()
    logger.info("S3 sync service stopped")
    return {"message": "S3 sync service stopped"}


@router.post("/sync")
async def sync_s3_sync_service(s3_sync_service: S3_SyncServiceDependency):
    """Trigger one sync pass."""
    await s3_sync_service.sync_once()


def main(api_port: int, s3_sync_service: S3SyncServiceBase):
    """Run the FastAPI app with the S3SyncService."""
    setup_logging()

    app = FastAPI(title="S3 Sync Service API")
    app.include_router(router, prefix="/api")
    app.get("/")(lambda: "alive")
    app.state.s3_sync_service = s3_sync_service

    logger.info("Starting S3SyncService API on port %d", api_port)
    uvicorn.run(app, port=api_port, log_config=None)


if __name__ == "__main__":
    auto_cli(main)
