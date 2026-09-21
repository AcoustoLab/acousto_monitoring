"""Yandex Cloud S3 client via boto3."""

import boto3

from pydantic import BaseModel, SecretStr
from pydantic_settings import SettingsConfigDict, BaseSettings
from src.concept.s3_sync_service import S3StorageClient

import logging
from pathlib import Path

from botocore.config import Config


logger = logging.getLogger(__name__)

_ENDPOINT = "https://storage.yandexcloud.net"
_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class YandexS3Config(BaseModel):
    """Non-secret S3 config loaded from YAML."""

    bucket: str
    region: str = "ru-central1"
    prefix: str = ""


class YandexS3Credentials(BaseSettings):
    """Secret S3 credentials loaded from .env or environment."""

    model_config = SettingsConfigDict(
        env_prefix="YANDEX_S3_",
        env_file=(
            _PROJECT_ROOT / ".env",
            _PROJECT_ROOT / ".env.local",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    access_key: SecretStr = SecretStr("")
    secret_key: SecretStr = SecretStr("")


class YandexS3Client(S3StorageClient):
    """Upload objects to Yandex Cloud S3."""

    def __init__(self, config: YandexS3Config) -> None:
        credentials = YandexS3Credentials()

        self._bucket = config.bucket
        self._prefix = config.prefix

        self._s3 = boto3.client(  # type: ignore[reportUnknownMemberType]
            "s3",
            endpoint_url=_ENDPOINT,
            region_name=config.region,
            aws_access_key_id=credentials.access_key.get_secret_value(),
            aws_secret_access_key=credentials.secret_key.get_secret_value(),
            config=_RETRY_CONFIG,
        )

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}/{key}" if self._prefix else key

    def upload(self, local_path: Path, key: str) -> None:
        full_key = self._full_key(key)
        logger.info("Uploading %s -> s3://%s/%s", local_path, self._bucket, full_key)
        self._s3.upload_file(str(local_path), self._bucket, full_key)
