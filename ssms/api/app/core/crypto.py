"""Field-level encryption (AES-256-GCM) and keyed blind indexes (HMAC-SHA256) for personal data.

Ciphertext layout: version(1) | key_id(1) | nonce(12) | ciphertext+tag. The field name is the
associated data, so a phone ciphertext cannot be pasted into the NIDA column and still decrypt.
"""

import hashlib
import hmac
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

FORMAT_VERSION = 1


class CryptoNotConfigured(RuntimeError):
    pass


class FieldCipher:
    def __init__(self, keys: dict[int, bytes], active_key_id: int, blind_key: bytes):
        self._keys = keys
        self._active = active_key_id
        self._blind_key = blind_key

    def encrypt(self, value: str, field: str) -> bytes:
        if self._active not in self._keys:
            raise CryptoNotConfigured("no active encryption key (SSMS_ENC_KEYS)")
        nonce = os.urandom(12)
        ct = AESGCM(self._keys[self._active]).encrypt(nonce, value.encode(), field.encode())
        return bytes([FORMAT_VERSION, self._active]) + nonce + ct

    def decrypt(self, blob: bytes, field: str) -> str:
        if not blob or blob[0] != FORMAT_VERSION:
            raise ValueError("unknown ciphertext format")
        key = self._keys.get(blob[1])
        if key is None:
            raise CryptoNotConfigured(f"encryption key {blob[1]} not loaded")
        return AESGCM(key).decrypt(blob[2:14], blob[14:], field.encode()).decode()

    def blind_index(self, value: str, field: str) -> bytes:
        if not self._blind_key:
            raise CryptoNotConfigured("no blind index key (SSMS_BLIND_INDEX_KEY)")
        return hmac.new(self._blind_key, f"{field}:{value}".encode(), hashlib.sha256).digest()

    def needs_rotation(self, blob: bytes) -> bool:
        return len(blob) > 1 and blob[1] != self._active


@lru_cache
def get_cipher() -> FieldCipher:
    s = get_settings()
    return FieldCipher(s.encryption_keys(), s.enc_active_key_id, s.blind_key())
