from typing import Literal, Any
from pydantic import GetCoreSchemaHandler, ValidatorFunctionWrapHandler
from pydantic import BaseModel
from pydantic_core import core_schema
import base64
import numpy as np


class _SerializedNDArrayData(BaseModel):
    type: Literal["numpy"]
    dtype: str
    shape: list[int]
    bytes: str


class SerializedNDArray:
    """Helper for serializing and deserializing `numpy.ndarray` objects.

    Usage example:
    ```py
    class A(BaseModel):
        tensor: Annotated[numpy.ndarray, SerializedNDArray]
    ```
    """

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: GetCoreSchemaHandler):
        return core_schema.no_info_wrap_validator_function(
            function=cls.validate,
            schema=core_schema.is_instance_schema(np.ndarray),
            serialization=core_schema.plain_serializer_function_ser_schema(
                cls.serialize,
                return_schema=handler.generate_schema(_SerializedNDArrayData),
            ),
        )

    @staticmethod
    def validate(
        value: dict[str, Any] | np.ndarray, handler: ValidatorFunctionWrapHandler
    ) -> np.ndarray:
        """Validate or coerce a value into a `numpy.ndarray`.

        Accepts either a ``numpy.ndarray`` instance or a mapping matching
        ``_SerializedNDArrayData`` and returns a reconstructed ``numpy.ndarray``.
        """
        if isinstance(value, np.ndarray):
            return value

        arr_data = _SerializedNDArrayData(**value)

        data = base64.b64decode(arr_data.bytes)
        # Reconstruct the array from raw bytes, using stored dtype, shape.
        return np.ndarray(
            shape=tuple(arr_data.shape),
            dtype=np.dtype(arr_data.dtype),
            buffer=bytearray(data),
        )

    @staticmethod
    def serialize(array: np.ndarray) -> _SerializedNDArrayData:
        """Serialize a ``numpy.ndarray`` into a Pydantic-friendly data model.

        The returned ``_SerializedNDArrayData`` contains metadata required to
        reconstruct the array (dtype, shape) and a
        base64-encoded byte payload of the array buffer.
        """
        # Make a contiguous C-order copy so the serialized bytes represent
        # the underlying buffer consistently.
        arr = np.ascontiguousarray(array)
        return _SerializedNDArrayData(
            type="numpy",
            dtype=str(arr.dtype),
            shape=list(arr.shape),
            bytes=base64.b64encode(arr.tobytes()).decode(),
        )
