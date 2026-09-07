"""Fernet encryption for secrets GeoLens stores at rest (OAUTH-02): covers
``OAuthProvider.client_secret_encrypted`` and ``.idp_certificate``.

Keys are read in this order: ``SECRET_ENCRYPTION_KEY``, then
``_PREVIOUS``, then a key derived from ``JWT_SECRET_KEY`` via HKDF. Writes
use the first key; reads try each in turn — so a dedicated key can be set
without breaking old ciphertexts, and the JWT secret can then rotate freely
(#1871).

``decrypt_secret``/``rotate_secret`` raise
``cryptography.fernet.InvalidToken`` when no configured key opens the value.
"""

import base64

from cryptography.fernet import Fernet, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def _jwt_derived_fernet() -> Fernet:
    from app.core.config import settings

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


def _get_fernet() -> MultiFernet:
    """Build the key chain. Its first entry is the one writes use."""
    from app.core.config import settings

    keys = [
        Fernet(configured.get_secret_value())
        for configured in (
            settings.secret_encryption_key,
            settings.secret_encryption_key_previous,
        )
        if configured is not None
    ]
    # fix(#1871): the JWT-derived key stays last forever. It is the only key
    # that opens a ciphertext written before a dedicated key was configured.
    keys.append(_jwt_derived_fernet())
    return MultiFernet(keys)


def encrypt_secret(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def rotate_secret(ciphertext: str) -> str:
    """Re-encrypt a stored secret under the first key in the chain."""
    return _get_fernet().rotate(ciphertext.encode()).decode()
