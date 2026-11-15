"""Local filesystem storage for uploaded files.

Files are content-addressed per firm: <storage_dir>/<firm_id>/<sha256>.pdf, so storing
the same bytes twice is a no-op (idempotent).
"""

import hashlib
import uuid
from functools import lru_cache
from pathlib import Path

from app.config import get_settings


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, firm_id: uuid.UUID, data: bytes) -> tuple[str, str]:
        """Persist bytes; returns (relative_path, sha256)."""
        digest = sha256_of(data)
        relative = f"{firm_id}/{digest}.pdf"
        path = self.root / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)  # atomic rename: readers never see a half-written file
        return relative, digest

    def read(self, relative_path: str) -> bytes:
        return (self.root / relative_path).read_bytes()

    def path_of(self, relative_path: str) -> Path:
        return self.root / relative_path


@lru_cache
def get_storage() -> LocalStorage:
    return LocalStorage(get_settings().storage_dir)
