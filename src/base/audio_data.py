"""Reusable audio collector data model."""

from datetime import UTC, datetime
from typing import Any
import uuid
from pydantic import Field

from toy import ToyCollectorServiceData


class BaseAudioCollectorServiceData(ToyCollectorServiceData):
    """audio data for storage and transport."""

    sample_rate: int = Field(default=44100)
    collected_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    recording_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    metadata: dict[str, Any] = Field(default_factory=dict)
