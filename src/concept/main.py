"""123."""

import numpy as np
from datetime import datetime
from abc import ABC, abstractmethod
from pathlib import Path


class Device:
    """Simple device."""

    def __init__(self):
        """Initialize the device."""
        self.buffer: list[float] = []

    def record(self):
        """Record data."""
        num_samples = np.random.randint(512, 2048)  # Simulate variable sample size
        data = np.random.rand(num_samples)
        self.buffer.extend(data)


class AbsCollector(ABC):
    """Abstract collector class."""

    @abstractmethod
    def collect(self, num_samples: int) -> np.ndarray:
        """Collect data."""


class DataCollector(AbsCollector):
    """Data collector implementation."""

    def __init__(self):
        super().__init__()
        self.device = Device()

    def collect(self, num_samples: int) -> np.ndarray:

        while len(self.device.buffer) < num_samples:
            self.device.record()

        data = self.device.buffer[:num_samples]
        self.device.buffer = self.device.buffer[num_samples:]

        return np.array(data)


class AbstractStorage(ABC):
    """Abstract storage class."""

    @abstractmethod
    def save(self, data: np.ndarray, folder: Path):
        """Save data."""


class DataStorage(AbstractStorage):
    """Data storage implementation."""

    def save(self, data: np.ndarray, folder: Path):
        filename = f"data_{datetime.now().timestamp()}.npy"
        np.save(folder / filename, data)
        print(f"Data saved to {folder / filename}")


data_collector = DataCollector()
data_storage = DataStorage()


# if __name__ == "__main__":
#     for _ in range(10):
#         # Data collector
#         data = data_collector.collect(1024)

#         # Data storage
#         data_storage.save(data, Path("."))
#         time.sleep(1)  # Simulate time delay between collections
