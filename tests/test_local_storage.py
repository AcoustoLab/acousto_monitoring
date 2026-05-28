"""Test the local storage service."""

from unittest.mock import patch

from pathlib import Path
import numpy as np
import pytest

from base.local_storage import LocalAudioStorageConfig, LocalAudioStorageService
from base.audio_data import BaseAudioCollectorServiceData


from concept.storage_service import CollectorMessage


@pytest.fixture()
def storage(tmp_path: Path) -> LocalAudioStorageService:
    """Fixture for LocalAudioStorageService with a temporary data root."""
    config = LocalAudioStorageConfig(
        zmq_sub_addrs=[],  # no real zmq in tests
        storage_id="test",
        data_root=str(tmp_path / "data"),
    )
    with patch.object(LocalAudioStorageService, "_add_zmq_subcription"):
        svc = LocalAudioStorageService(config)
    return svc


def test_connect_db_creates_dir(storage: LocalAudioStorageService, tmp_path: Path):
    """_connect_db must have created the data_root directory."""
    assert (tmp_path / "data").is_dir()


@pytest.mark.asyncio
async def test_write_db_creates_files(storage: LocalAudioStorageService):
    """write_db should produce a .wav and a .json file."""
    audio = np.zeros(1000, dtype=np.float32)
    item = BaseAudioCollectorServiceData(data=audio, collected_at="2024-01-15T10:30:00+00:00")
    msg = CollectorMessage(uid="abc123", data=item)

    await storage.write_db(msg)

    wavs = list(storage.data_root.glob("**/*.wav"))
    jsons = list(storage.data_root.glob("**/*.json"))
    assert len(wavs) == 1
    assert len(jsons) == 1


@pytest.mark.asyncio
async def test_status_file_count(storage: LocalAudioStorageService):
    """status() returns the correct number of wav files."""
    audio = np.zeros(100, dtype=np.float32)
    for i in range(3):
        item = BaseAudioCollectorServiceData(
            data=audio,
            collected_at=f"2024-01-{15 + i:02d}T10:00:00+00:00",
        )
        msg = CollectorMessage(uid=f"uid{i}", data=item)
        await storage.write_db(msg)

    result = await storage.status()
    assert result["file_count"] == 3
    assert result["storage_id"] == "test"
    assert result["storage_type"] == "local"
    assert result["data_root"] == str(storage.data_root)
