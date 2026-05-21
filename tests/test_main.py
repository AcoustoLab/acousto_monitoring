"""Test for the main module."""

from concept import main
from pathlib import Path


def test_main(tmp_path: Path):
    """Test the main function."""
    device = main.Device()
    device.record()

    collector = main.DataCollector()
    data = collector.collect(10)
    assert len(data) == 10

    storage = main.DataStorage()
    storage.save(data, tmp_path)
