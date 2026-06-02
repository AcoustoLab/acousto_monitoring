"""Tests for local_storage.py."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from base.audio_data import BaseAudioCollectorServiceData
from base.local_storage import (
    LocalAudioStorageConfig,
    LocalAudioStorageService,
    _write_wav_atomic,  # type: ignore
    router,
)
from concept.storage_service import CollectorMessage


@pytest.fixture()
def storage(tmp_path: Path) -> LocalAudioStorageService:
    """Fixture to create a LocalAudioStorageService instance with a temporary data directory."""
    config = LocalAudioStorageConfig(
        zmq_sub_addrs=[],
        storage_id="test-id",
        data_root=str(tmp_path / "data"),
    )
    return LocalAudioStorageService(config)


def make_msg(
    uid: str = "uid1",
    collected_at: str = "2024-03-15T10:30:00+00:00",
) -> CollectorMessage[Any]:
    """Helper to create a CollectorMessage with BaseAudioCollectorServiceData for testing."""
    item = BaseAudioCollectorServiceData(
        data=np.zeros(512, dtype=np.float32),
        collected_at=collected_at,
    )
    return CollectorMessage(uid=uid, data=item.model_dump())


def test_write_wav_1d(tmp_path: Path) -> None:
    """"Test that _write_wav_atomic can write a 1D mono audio array."""
    _write_wav_atomic(tmp_path / "out.wav", np.zeros(1000, dtype=np.float32), 44100)
    assert (tmp_path / "out.wav").exists()


def test_write_wav_2d_stereo(tmp_path: Path) -> None:
    """"Test that _write_wav_atomic can write a 2D stereo audio array."""
    _write_wav_atomic(tmp_path / "out.wav", np.zeros((1000, 2), dtype=np.float32), 44100)
    assert (tmp_path / "out.wav").exists()


def test_write_wav_3d_raises() -> None:
    """Test that _write_wav_atomic raises an error for 3D audio arrays."""
    with pytest.raises(ValueError, match="1D mono or 2D"):
        _write_wav_atomic(Path("/tmp/x.wav"), np.zeros((10, 2, 2), dtype=np.float32), 44100)


def test_write_wav_empty_channels_raises() -> None:
    """Test that _write_wav_atomic raises an error for 2D arrays with zero channels."""
    with pytest.raises(ValueError, match="at least one channel"):
        _write_wav_atomic(Path("/tmp/x.wav"), np.zeros((10, 0), dtype=np.float32), 44100)


def test_connect_db_creates_directory(storage: LocalAudioStorageService, tmp_path: Path) -> None:
    """Test that _connect_db creates the data root directory."""
    assert (tmp_path / "data").is_dir()


@pytest.mark.asyncio
async def test_write_db_creates_wav_and_json(storage: LocalAudioStorageService) -> None:
    """Test that write_db creates both WAV and JSON files for a given CollectorMessage."""
    await storage.write_db(make_msg())
    assert len(list(storage.data_root.glob("**/*.wav"))) == 1
    assert len(list(storage.data_root.glob("**/*.json"))) == 1


@pytest.mark.asyncio
async def test_write_db_json_has_correct_fields(storage: LocalAudioStorageService) -> None:
    """Test that the JSON metadata file created by write_db has the expected fields."""
    await storage.write_db(make_msg(uid="abc"))
    meta = json.loads(next(storage.data_root.glob("**/*.json")).read_text())
    assert meta["uid"] == "abc"
    assert "recording_id" in meta
    assert meta["sample_rate"] == 44100


@pytest.mark.asyncio
async def test_status_file_count(storage: LocalAudioStorageService) -> None:
    """Test that the status method returns the correct file count and storage info."""
    for i in range(3):
        await storage.write_db(
            make_msg(uid=f"u{i}", collected_at=f"2024-03-{15 + i:02d}T10:00:00+00:00")
        )
    result = await storage.status()
    assert result["file_count"] == 3
    assert result["storage_id"] == "test-id"
    assert result["storage_type"] == "local"


@pytest.mark.asyncio
async def test_sync_returns_none(storage: LocalAudioStorageService) -> None:
    """Test that the sync method returns None."""
    item = BaseAudioCollectorServiceData(data=np.zeros(10, dtype=np.float32))
    assert await storage.sync(item) is None


@pytest.mark.asyncio
async def test_start_is_idempotent(storage: LocalAudioStorageService) -> None:
    """Test that calling start multiple times does not create multiple tasks."""
    with patch.object(storage, "_open_zmq_subscriptions"):
        await storage.start()
        first_task = storage._writing_task  # type: ignore
        await storage.start()
        assert storage._writing_task is first_task  # type: ignore
        await storage.stop()


@pytest.fixture()
def client(storage: LocalAudioStorageService) -> TestClient:
    """Fixture to create a TestClient with the storage service dependency."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.storage = storage
    return TestClient(app)


def test_route_status(client: TestClient) -> None:
    """Test that the /api/status route returns the correct storage status."""
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.json()["storage_id"] == "test-id"


def test_route_start(client: TestClient) -> None:
    """Test that the /api/start route starts the storage service without errors."""
    with patch.object(client.app.state.storage, "_open_zmq_subscriptions"):  # type: ignore
        response = client.post("/api/start")
    assert response.status_code == 200
    assert response.json() == {"message": "Storage started"}


def test_route_stop(client: TestClient) -> None:
    """Test that the /api/stop route stops the storage service without errors."""
    response = client.post("/api/stop")
    assert response.status_code == 200
    assert response.json() == {"message": "Storage stopped"}
