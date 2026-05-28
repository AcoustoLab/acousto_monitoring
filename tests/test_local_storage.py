"""Test the local storage service."""

from unittest.mock import patch

from pathlib import Path
import numpy as np
import pytest

from base.local_storage import LocalAudioStorageConfig, LocalAudioStorageService
from base.audio_data import BaseAudioCollectorServiceData


from base.local_storage import _pcm16_audio  # type: ignore
from concept.storage_service import CollectorMessage


def test_pcm16_float_clipped():
    """Float audio in [-1, 1] is scaled to int16 range."""
    audio = np.array([0.0, 1.0, -1.0], dtype=np.float32)
    result = _pcm16_audio(audio)
    assert result.dtype == np.dtype("<i2")
    assert result[1] == 32767
    assert result[2] == -32767


def test_pcm16_int_passthrough():
    """Integer audio is just clipped and cast, not scaled."""
    audio = np.array([0, 100, -100], dtype=np.int32)
    result = _pcm16_audio(audio)
    assert result.dtype == np.dtype("<i2")
    assert list(result) == [0, 100, -100]


def test_pcm16_2d_stereo():
    """2D stereo array is accepted."""
    audio = np.zeros((1000, 2), dtype=np.float32)
    result = _pcm16_audio(audio)
    assert result.shape == (1000, 2)


def test_pcm16_invalid_shape():
    """3D array raises ValueError."""
    audio = np.zeros((10, 2, 2), dtype=np.float32)
    with pytest.raises(ValueError):
        _pcm16_audio(audio)


def test_pcm16_empty_channels():
    """2D array with 0 channels raises ValueError."""
    audio = np.zeros((10, 0), dtype=np.float32)
    with pytest.raises(ValueError):
        _pcm16_audio(audio)


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
