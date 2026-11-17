"""Document storage. LocalStorage for development; use an S3/MinIO implementation in production."""
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...


class LocalStorage:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or get_settings().storage_dir).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("storage key escapes the storage root")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()
