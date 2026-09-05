"""Fernet encryption for the secrets GeoLens stores at rest (OAUTH-02).

Covers ``OAuthProvider.client_secret_encrypted`` and
``OAuthProvider.idp_certificate``.

Keys are read in this order: ``SECRET_ENCRYPTION_KEY``, then
``SECRET_ENCRYPTION_KEY_PREVIOUS``, then a key derived from ``JWT_SECRET_KEY``
via HKDF. Writes always use the first key in that list; reads try every key in
turn. Setting a dedicated key therefore leaves existing ciphertexts readable
and takes every later write off the JWT secret, so the JWT secret can be
rotated on its own (#1871).

``decrypt_secret`` and ``rotate_secret`` raise
``cryptography.fernet.InvalidToken`` when no configured key opens the value.
"""

import base64

from cryptography.fernet import Fernet, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def _jwt_derived_fernet() -> Fernet:
    """Derive the legacy Fernet key from the app's JWT secret using HKDF."""
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
    """Encrypt a plaintext secret for database storage."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a stored secret for use."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def rotate_secret(ciphertext: str) -> str:
    """Re-encrypt a stored secret under the first key in the chain."""
    return _get_fernet().rotate(ciphertext.encode()).decode()
