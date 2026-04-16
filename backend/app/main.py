"""Compatibility shim for the legacy API entrypoint."""

from app.api.main import app, health, lifespan, seed_initial_admin, seed_roles

__all__ = ["app", "health", "lifespan", "seed_initial_admin", "seed_roles"]
