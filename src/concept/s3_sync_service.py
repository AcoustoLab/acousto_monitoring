"""S3 Sync Service."""

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel


class S3StorageClient(ABC):
    """S3 compatible object storage client."""

    @abstractmethod
    def upload(self, local_path: Path, key: str) -> None:
        """Upload a local file to object storage under the given key."""


    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete an object from storage by key."""


class S3SyncConfigBase(BaseModel):
    """Configuration for S3 synchronization."""


class S3SyncService(ABC):
    """S3 synchronization service to sync local files to S3 storage."""

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def sync_once(self) -> None:
        """One pass: find new files → upload → mark."""
