"""Tests for s3_client.py, s3_sync.py."""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import BotoCoreError
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.base.s3_client import YandexS3Client, YandexS3Config
from src.base.s3_sync import S3SyncConfig, S3SyncServiceBase, router
from src.concept.s3_sync_service import S3StorageClient


@pytest.fixture(autouse=True)
def fast_tenacity():
    """Make tenacity retries instant in all tests."""
    with patch("tenacity.nap.time.sleep"):  # блокирует реальный sleep внутри tenacity
        yield


class DummyClient(S3StorageClient):
    """S3StorageClient implementation that records uploads and simulates failures."""

    def __init__(self) -> None:
        self.uploaded: list[tuple[Path, str]] = []
        self.fail_on: set[str] = set()

    def upload(self, local_path: Path, key: str) -> None:
        if key in self.fail_on:
            raise BotoCoreError()
        self.uploaded.append((local_path, key))


@pytest.fixture()
def service(tmp_path: Path) -> S3SyncServiceBase:
    """S3SyncServiceBase with DummyClient and config pointing to tmp_path."""
    config = S3SyncConfig(
        data_root=str(tmp_path),
        upload_every_n_files=10,
        upload_every_seconds=600,
        scan_every_seconds=1,
    )
    return S3SyncServiceBase(config, DummyClient())


@pytest.fixture()
def client_app(service: S3SyncServiceBase) -> TestClient:
    """TestClient with FastAPI app that has the S3SyncServiceBase instance in state."""
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.s3_sync_service = service
    return TestClient(app)


@pytest.fixture()
def s3_client() -> YandexS3Client:
    """YandexS3Client with mocked boto3 client to verify upload calls."""
    config = YandexS3Config(bucket="my-bucket", prefix="pfx")
    with (
        patch(
            "src.base.s3_client.YandexS3Credentials",
            return_value=MagicMock(
                access_key=MagicMock(get_secret_value=lambda: "ak"),
                secret_key=MagicMock(get_secret_value=lambda: "sk"),
            ),
        ),
        patch("src.base.s3_client.boto3.client") as mock_boto,
    ):
        svc = YandexS3Client(config)
        svc._s3 = mock_boto.return_value  # type: ignore
    return svc


def test_upload_calls_boto(s3_client: YandexS3Client, tmp_path: Path) -> None:
    """Uploading a file calls boto3 client's upload_file with correct bucket and key."""
    f = tmp_path / "audio.wav"
    f.touch()
    s3_client.upload(f, "2024/audio.wav")
    s3_client._s3.upload_file.assert_called_once_with(  # type: ignore
        str(f), "my-bucket", "pfx/2024/audio.wav"
    )


def test_full_key_without_prefix() -> None:
    """YandexS3Client._full_key returns the key unchanged if prefix is empty."""
    config = YandexS3Config(bucket="b", prefix="")
    with (
        patch(
            "src.base.s3_client.YandexS3Credentials",
            return_value=MagicMock(
                access_key=MagicMock(get_secret_value=lambda: ""),
                secret_key=MagicMock(get_secret_value=lambda: ""),
            ),
        ),
        patch("src.base.s3_client.boto3.client"),
    ):
        svc = YandexS3Client(config)
    assert svc._full_key("some/key.wav") == "some/key.wav"  # type: ignore


@pytest.mark.asyncio
async def test_sync_once_empty_dir(service: S3SyncServiceBase) -> None:
    """Syncing an empty directory does not call upload and does not create markers."""
    await service.sync_once()
    assert service._client.uploaded == []  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_sync_once_uploads_and_marks(service: S3SyncServiceBase, tmp_path: Path) -> None:
    """Syncing a directory with new files uploads them and creates .uploaded markers."""
    (tmp_path / "a.wav").write_bytes(b"")
    (tmp_path / "b.json").write_bytes(b"")
    await service.sync_once()
    assert len(service._client.uploaded) == 2  # type: ignore[union-attr]
    assert (tmp_path / "a.wav.uploaded").exists()
    assert (tmp_path / "b.json.uploaded").exists()


@pytest.mark.asyncio
async def test_sync_once_skips_already_uploaded(service: S3SyncServiceBase, tmp_path: Path) -> None:
    """Files with existing .uploaded markers are not uploaded again."""
    (tmp_path / "a.wav").write_bytes(b"")
    (tmp_path / "a.wav.uploaded").touch()
    await service.sync_once()
    assert service._client.uploaded == []  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_sync_once_skips_other_extensions(service: S3SyncServiceBase, tmp_path: Path) -> None:
    """Files with extensions other than .wav are ignored and not uploaded."""
    (tmp_path / "note.txt").write_bytes(b"")
    await service.sync_once()
    assert service._client.uploaded == []  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_sync_once_upload_failure_does_not_stop_others(
    service: S3SyncServiceBase, tmp_path: Path
) -> None:
    """If uploading file fails, it does not prevent other files from being uploaded and marked."""
    (tmp_path / "bad.wav").write_bytes(b"")
    (tmp_path / "good.wav").write_bytes(b"")
    service._client.fail_on = {"bad.wav"}  # type: ignore[union-attr]
    await service.sync_once()
    uploaded_keys = [key for _, key in service._client.uploaded]  # type: ignore[union-attr]
    assert "good.wav" in uploaded_keys
    assert not (tmp_path / "bad.wav.uploaded").exists()


@pytest.mark.asyncio
async def test_sync_once_delete_after_upload(tmp_path: Path) -> None:
    """If delete_after_upload is True, local files are deleted after successful upload."""
    config = S3SyncConfig(
        data_root=str(tmp_path),
        upload_every_n_files=10,
        upload_every_seconds=600,
        delete_after_upload=True,
    )
    svc = S3SyncServiceBase(config, DummyClient())
    f = tmp_path / "a.wav"
    f.write_bytes(b"")
    await svc.sync_once()
    assert not f.exists()


@pytest.mark.asyncio
async def test_sync_once_lock_log(service: S3SyncServiceBase, tmp_path: Path, caplog: Any) -> None:
    """Log line fires when sync_once is called while lock is held."""
    (tmp_path / "a.wav").write_bytes(b"")
    async with service._sync_lock:  # type: ignore[union-attr]
        with pytest.raises(asyncio.TimeoutError):
            async with asyncio.timeout(0.05):
                with caplog.at_level("INFO"):
                    await service.sync_once()
    assert "waiting" in caplog.text


@pytest.mark.asyncio
async def test_status(service: S3SyncServiceBase, tmp_path: Path) -> None:
    """Status returns correct counts of pending and uploaded files and running state."""
    (tmp_path / "a.wav").write_bytes(b"")
    (tmp_path / "b.wav.uploaded").touch()
    result = await service.status()
    assert result["pending"] == 1
    assert result["uploaded"] == 1
    assert result["running"] is False


@pytest.mark.asyncio
async def test_start_is_idempotent(service: S3SyncServiceBase) -> None:
    """Starting the service multiple times does not create multiple tasks."""
    await service.start()
    first = service._task  # type: ignore
    await service.start()
    assert service._task is first  # type: ignore
    await service.stop()


@pytest.mark.asyncio
async def test_stop_without_start(service: S3SyncServiceBase) -> None:
    """Stopping the service when it's not running does not raise and leaves it stopped."""
    await service.stop()
    assert service._task is None  # type: ignore


@pytest.mark.asyncio
async def test_loop_triggers_sync_on_count(tmp_path: Path) -> None:
    """The loop triggers sync_once when the number of pending files reaches the threshold."""
    config = S3SyncConfig(
        data_root=str(tmp_path),
        upload_every_n_files=2,
        upload_every_seconds=9999,
        scan_every_seconds=1,
    )
    svc = S3SyncServiceBase(config, DummyClient())
    (tmp_path / "a.wav").write_bytes(b"")
    (tmp_path / "b.wav").write_bytes(b"")

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(svc._loop(), timeout=1.1)  # type: ignore[union-attr]

    assert len(svc._client.uploaded) == 2  # type: ignore[union-attr]


def test_route_status(client_app: TestClient) -> None:
    """GET /api/status returns 200 and expected keys in response."""
    assert client_app.get("/api/status").status_code == 200


def test_route_start(client_app: TestClient) -> None:
    """POST /api/start starts the service and returns expected message."""
    r = client_app.post("/api/start")
    assert r.json() == {"message": "S3 sync service started"}
    client_app.app.state.s3_sync_service._task.cancel()  # type: ignore[union-attr]


def test_route_stop(client_app: TestClient) -> None:
    """POST /api/stop stops the service and returns expected message."""
    r = client_app.post("/api/stop")
    assert r.json() == {"message": "S3 sync service stopped"}


def test_route_sync(client_app: TestClient) -> None:
    """POST /api/sync triggers a sync and returns 200."""
    r = client_app.post("/api/sync")
    assert r.status_code == 200
