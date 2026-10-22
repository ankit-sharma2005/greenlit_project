"""Encrypt/decrypt API keys at rest."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    """Get or create a Fernet instance from the app secret key."""
    app_secret = os.environ.get("APP_SECRET_KEY", "dev-insecure-key-change-me-0123456789")
    key_material = app_secret.encode("utf-8")[:32]
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"greenlit-provider-keys",
        iterations=100000,
        backend=default_backend(),
    )
    key = kdf.derive(key_material)
    return Fernet(key)


def encrypt_key(raw_key: str | None) -> str | None:
    """Encrypt a raw API key for storage. Returns None if input is None."""
    if not raw_key:
        return None
    f = _get_fernet()
    encrypted = f.encrypt(raw_key.encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt_key(encrypted_key: str | None) -> str | None:
    """Decrypt an API key for use. Returns None if input is None."""
    if not encrypted_key:
        return None
    f = _get_fernet()
    try:
        decrypted = f.decrypt(encrypted_key.encode("utf-8"))
        return decrypted.decode("utf-8")
    except Exception:
        return None
