"""Symmetric encryption for Moodle web-service tokens at rest."""
from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import DATA_DIR

_KEY_FILE = DATA_DIR / ".secret.key"


def _resolve_key(configured: str) -> bytes:
    if configured:
        return configured.encode()
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes().strip()
    key = Fernet.generate_key()
    _KEY_FILE.write_bytes(key)
    try:
        _KEY_FILE.chmod(0o600)
    except OSError:  # best effort on Windows
        pass
    return key


class Vault:
    def __init__(self, configured_key: str) -> None:
        self._f = Fernet(_resolve_key(configured_key))

    def encrypt(self, plain: str) -> str:
        return self._f.encrypt(plain.encode()).decode()

    def decrypt(self, blob: str) -> str | None:
        try:
            return self._f.decrypt(blob.encode()).decode()
        except (InvalidToken, ValueError):
            return None
