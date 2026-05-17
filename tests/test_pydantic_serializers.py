"""Tests for pydantic_serializers.py."""

import pytest
from concept.pydantic_serializers import SerializedNDArray
from pydantic import BaseModel
from typing import Annotated
import numpy as np


class SerializedNDArrayTestModel(BaseModel):
    """Test model for SerializedNDArray."""

    data: Annotated[np.ndarray, SerializedNDArray]


@pytest.mark.parametrize(
    "array",
    [
        np.random.rand(2, 3),
        np.random.rand(2, 3).T,
        np.random.rand(4, 5, 6),
        np.random.rand(4, 5, 6).astype(np.float32),
        (10 * np.random.rand(4, 5, 6)).astype(np.int16),
        (10 * np.random.rand(4, 5, 6)).astype(np.uint8),
    ],
)
def test_serialization(array: np.ndarray):
    """Test that a numpy array can be serialized and deserialized correctly."""
    serialized = SerializedNDArrayTestModel(data=array)
    deserialized = SerializedNDArrayTestModel(**serialized.model_dump())
    assert np.array_equal(array, deserialized.data)
