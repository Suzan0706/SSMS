"""File storage behind one small interface: a local folder (one server) or S3-compatible object storage.

Keys are built by the application (school id / area / object id / name), never taken from user input, and both
backends refuse anything that is not a plain relative key.
"""

import re
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

_KEY = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")


def check_key(key: str) -> str:
    if not _KEY.match(key) or ".." in key:
        raise ValueError("invalid storage key")
    return key


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        return self.root / check_key(key)

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3Storage:
    """Any S3-compatible store (MinIO, AWS S3, Wasabi...). A missing object raises FileNotFoundError, as locally."""

    def __init__(self, bucket: str, client):
        self.bucket, self.client = bucket, client

    @classmethod
    def from_settings(cls) -> "S3Storage":
        import boto3
        from botocore.config import Config

        s = get_settings()
        client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url or None,
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
        )
        return cls(s.s3_bucket, client)

    def put(self, key: str, data: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=check_key(key), Body=data)
        return key

    def get(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=check_key(key))["Body"].read()
        except self.client.exceptions.NoSuchKey as exc:
            raise FileNotFoundError(key) from exc

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=check_key(key))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=check_key(key))


@lru_cache
def get_storage() -> LocalStorage | S3Storage:
    s = get_settings()
    return S3Storage.from_settings() if s.storage_backend == "s3" else LocalStorage(s.storage_dir)
