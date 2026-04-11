"""Fernet encryption helpers for OAuth client secrets.

Derives a Fernet key from the application's JWT_SECRET_KEY via HKDF,
ensuring secrets are encrypted at rest in the database (OAUTH-02).
"""

import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def _get_fernet() -> Fernet:
    """Derive a Fernet key from the app's JWT secret using HKDF."""
    from app.config import settings

    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"geolens-oauth-secrets",
        info=b"fernet-key",
    )
    key = base64.urlsafe_b64encode(
        kdf.derive(settings.jwt_secret_key.get_secret_value().encode())
    )
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a plaintext secret for database storage."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a stored secret for use."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
