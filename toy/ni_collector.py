from src.concept.ni_collector_service import NICollectorService
from jsonargparse import auto_cli  # type: ignore

from concept.collector_service import CollectorService, AbstractCollectorService
from concept.collector_service import CollectorServiceConfig, CollectorServiceData
import time
import numpy as np
from concept.pydantic_serializers import SerializedNDArray

from typing import Annotated, cast

from concept.collector_service import get_app
import uvicorn

from jsonargparse import auto_cli  # type: ignore

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def main(
    api_port: int,
    collector: NICollectorService,  # type: ignore
):
    """Start the collector service."""
    # Create the FastAPI app and include the api router
    collector: AbstractCollectorService[CollectorServiceConfig, CollectorServiceData] = cast(
        AbstractCollectorService[CollectorServiceConfig, CollectorServiceData], collector
    )

    api_app = get_app(collector)

    # setup logging
    log_file = Path().cwd() / "logs" / f"collector_{collector.uid}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s (%(name)s) [%(levelname)s] %(message)s")

    file_handler = RotatingFileHandler(log_file, maxBytes=1 * 1024 * 1024, backupCount=5)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    collector_logger = logging.getLogger("concept.collector_service")
    collector_logger.addHandler(file_handler)
    collector_logger.addHandler(console_handler)
    collector_logger.setLevel(logging.DEBUG)

    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.addHandler(file_handler)
    uvicorn_logger.addHandler(console_handler)
    uvicorn_logger.setLevel(logging.INFO)

    # Start the FastAPI app
    uvicorn.run(api_app, port=api_port, log_config=None)


if __name__ == "__main__":
    auto_cli(main)