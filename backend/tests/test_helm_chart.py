"""Helm chart reconciliation guards.

Phase 268 FIX-SEC-01 H-32: The Helm chart's secret.yaml previously rendered a
``SECRET_KEY`` env var that no Pydantic Settings field consumed. The
application reads ``JWT_SECRET_KEY``, so a vanilla ``helm install`` with
``secrets.secretKey="..."`` resulted in a container whose ``JWT_SECRET_KEY``
was unset, and ``Settings()`` raised at startup. This test prevents that
class of drift by asserting:

1. The Helm secret template uses ``JWT_SECRET_KEY`` (matches Pydantic field name).
2. The ``values.yaml`` contains a ``jwtSecretKey`` key (not ``secretKey``).
3. The deprecated ``SECRET_KEY`` env-var name does NOT appear in the secret
   template (would silently break deployments).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELM_CHART = _REPO_ROOT / "deployment" / "helm" / "geolens"
_SECRET_TEMPLATE = _HELM_CHART / "templates" / "secret.yaml"
_VALUES = _HELM_CHART / "values.yaml"


def _read(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"Helm chart file not found at {path}")
    return path.read_text(encoding="utf-8")


def test_helm_secret_template_uses_jwt_secret_key() -> None:
    """The Helm secret renders JWT_SECRET_KEY (matches Pydantic field name).

    Closes Phase 268 H-32: the env var name MUST match the Pydantic Settings
    field ``jwt_secret_key`` (case-insensitive — Pydantic reads
    ``JWT_SECRET_KEY``). Any other name leaves the field unset and the
    container crashes at startup.
    """
    content = _read(_SECRET_TEMPLATE)
    assert "JWT_SECRET_KEY:" in content, (
        "deployment/helm/geolens/templates/secret.yaml must render a "
        "JWT_SECRET_KEY env var (matches Pydantic Settings field "
        "jwt_secret_key). H-32 regression."
    )


def test_helm_secret_template_does_not_use_legacy_secret_key() -> None:
    """The deprecated SECRET_KEY env-var name must not reappear.

    The application reads JWT_SECRET_KEY only — any rename back to SECRET_KEY
    silently breaks deploys.
    """
    content = _read(_SECRET_TEMPLATE)
    # Match a YAML key (key followed by colon) — avoids false positive on
    # comments or strings that mention SECRET_KEY incidentally.
    assert "SECRET_KEY:" not in content or "JWT_SECRET_KEY:" in content, (
        "Helm secret.yaml must not render a bare SECRET_KEY env var; the "
        "Pydantic Settings field is JWT_SECRET_KEY. H-32 regression."
    )
    # Strict: the only SECRET_KEY-suffixed line should be JWT_SECRET_KEY.
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("SECRET_KEY:"):
            pytest.fail(
                "Helm secret.yaml contains 'SECRET_KEY:' which is not read "
                "by the application. Use 'JWT_SECRET_KEY:' instead. H-32."
            )


def test_helm_values_uses_jwt_secret_key_naming() -> None:
    """values.yaml must use jwtSecretKey (matches the env-var rename).

    The previous ``secrets.secretKey`` name is misleading and was the source
    of H-32 — operators set ``secrets.secretKey`` and got a broken container.
    """
    content = _read(_VALUES)
    assert "jwtSecretKey:" in content, (
        "deployment/helm/geolens/values.yaml must declare a 'jwtSecretKey' "
        "key under 'secrets:'. H-32 regression."
    )
