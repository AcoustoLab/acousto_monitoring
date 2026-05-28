"""Tests for storage_service.py and local_storage.py."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from base.local_storage import _write_wav_atomic  # type: ignore[import]
from base.local_storage import LocalAudioStorageConfig, LocalAudioStorageService
from base.audio_data import BaseAudioCollectorServiceData
from concept.storage_service import CollectorMessage


def test_write_wav_1d(tmp_path: Path):
    """Test that _write_wav_atomic successfully writes a 1D mono audio array to a WAV file."""
    _write_wav_atomic(tmp_path / "out.wav", np.zeros(1000, dtype=np.float32), 44100)
    assert (tmp_path / "out.wav").exists()


def test_write_wav_2d_stereo(tmp_path: Path):
    """Test that _write_wav_atomic successfully writes a 2D stereo audio array to a WAV file."""
    _write_wav_atomic(tmp_path / "out.wav", np.zeros((1000, 2), dtype=np.float32), 44100)
    assert (tmp_path / "out.wav").exists()


def test_write_wav_3d_raises():
    """Test that _write_wav_atomic raises a ValueError when given a 3D audio array."""
    with pytest.raises(ValueError, match="1D mono or 2D"):
        _write_wav_atomic(Path("/tmp/x.wav"), np.zeros((10, 2, 2), dtype=np.float32), 44100)


def test_write_wav_empty_channels_raises():
    """Test that _write_wav_atomic raises a ValueError when given a 2D array with zero channels."""
    with pytest.raises(ValueError, match="at least one channel"):
        _write_wav_atomic(Path("/tmp/x.wav"), np.zeros((10, 0), dtype=np.float32), 44100)


@pytest.fixture()
def storage(tmp_path: Path) -> LocalAudioStorageService:
    """Helper to create a LocalAudioStorageService with a temporary data root for testing."""
    config = LocalAudioStorageConfig(
        zmq_sub_addrs=[],
        storage_id="test-id",
        data_root=str(tmp_path / "data"),
    )
    return LocalAudioStorageService(config)


def make_msg(
    uid: str = "uid1",
    collected_at: str = "2024-03-15T10:30:00+00:00",
) -> CollectorMessage[BaseAudioCollectorServiceData]:
    """Helper to create a CollectorMessage with a BaseAudioCollectorServiceData item."""
    item = BaseAudioCollectorServiceData(
        data=np.zeros(512, dtype=np.float32),
        collected_at=collected_at,
    )
    return CollectorMessage(uid=uid, data=item)


@pytest.mark.asyncio
async def test_status_file_count(storage: LocalAudioStorageService):
    """Test that status() returns the correct file count and storage info."""
    for i in range(3):
        await storage.write_db(
            make_msg(uid=f"u{i}", collected_at=f"2024-03-{15 + i:02d}T10:00:00+00:00")
        )
    result = await storage.status()
    assert result["file_count"] == 3
    assert result["storage_id"] == "test-id"
    assert result["storage_type"] == "local"


@pytest.mark.asyncio
async def test_sync_returns_none(storage: LocalAudioStorageService):
    """Test that sync() method returns None."""
    item = BaseAudioCollectorServiceData(data=np.zeros(10, dtype=np.float32))
    assert await storage.sync(item) is None


@pytest.mark.asyncio
async def test_start_is_idempotent(storage: LocalAudioStorageService):
    """Second start() call is a no-op when already running."""
    with patch.object(storage, "_open_zmq_subscriptions"):
        await storage.start()
        first_task = storage._writing_task  # type: ignore[assignment]
        await storage.start()
        assert storage._writing_task is first_task  # type: ignore[comparison-overlap]
        await storage.stop()
