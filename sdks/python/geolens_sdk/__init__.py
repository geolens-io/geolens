# SPDX-License-Identifier: Apache-2.0
"""A client library for accessing GeoLens API.

Public exports:
    GeolensClient    — high-level wrapper with bearer/api-key/anonymous auth modes.
    AuthenticatedClient, Client — generator's underlying clients (advanced use).

Typical usage::

    from geolens_sdk import GeolensClient
    client = GeolensClient(base_url="https://geolens.example.com", bearer_token="<JWT>")

This file is hand-maintained alongside ``auth.py``; ``make sdks`` cp-stashes it
across regenerations so the public re-export survives ``--overwrite``.
"""

from .auth import GeolensClient
from .client import AuthenticatedClient, Client

__all__ = (
    "GeolensClient",
    "AuthenticatedClient",
    "Client",
)
