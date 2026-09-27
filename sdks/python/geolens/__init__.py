# SPDX-License-Identifier: Apache-2.0
"""A client library for accessing GeoLens API.

Public exports:
    GeolensClient    — high-level wrapper with bearer/api-key/anonymous auth modes.
    cog_download     — COG download that works on every storage backend.
    AuthenticatedClient, Client — generator's underlying clients (advanced use).

Typical usage::

    from geolens import GeolensClient
    client = GeolensClient(base_url="https://geolens.example.com/api", bearer_token="<JWT>")

This file is hand-maintained alongside ``auth.py`` and ``cog_download.py``;
``make sdks`` cp-stashes all three across regenerations so they survive
``--overwrite``.
"""

from . import cog_download
from .auth import GeolensClient
from .client import AuthenticatedClient, Client

__all__ = (
    "GeolensClient",
    "cog_download",
    "AuthenticatedClient",
    "Client",
)
