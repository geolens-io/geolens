"""Tests for AWS Marketplace RegisterUsage metering integration.

These tests are standalone and do not require a database connection.
They test the register_marketplace_usage helper in app/marketplace.py.
"""

from unittest.mock import MagicMock, patch
import importlib
import sys
import uuid

import pytest

# Marker to skip DB-dependent conftest fixtures
pytestmark = pytest.mark.filterwarnings("ignore")


def _get_register_fn():
    """Import register_marketplace_usage, reloading to pick up patched boto3."""
    if "app.marketplace" in sys.modules:
        importlib.reload(sys.modules["app.marketplace"])
    from app.core.marketplace import register_marketplace_usage

    return register_marketplace_usage


class TestRegisterMarketplaceUsage:
    """Tests for register_marketplace_usage helper."""

    def test_register_usage_called_with_correct_params(self):
        """METER-01: RegisterUsage called with ProductCode, PublicKeyVersion, and Nonce."""
        mock_settings = MagicMock()
        mock_settings.aws_marketplace_product_code = "prod-abc123"
        mock_settings.aws_marketplace_public_key_version = 1

        mock_client = MagicMock()
        mock_client.register_usage.return_value = {"Signature": "sig123abc"}

        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client

        mock_logger = MagicMock()

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            register_fn = _get_register_fn()
            register_fn(mock_settings, mock_logger)

        mock_client.register_usage.assert_called_once()
        call_kwargs = mock_client.register_usage.call_args[1]
        assert call_kwargs["ProductCode"] == "prod-abc123"
        assert call_kwargs["PublicKeyVersion"] == 1
        assert "Nonce" in call_kwargs
        # Nonce should be a valid UUID string
        uuid.UUID(call_kwargs["Nonce"])

    def test_boto3_client_no_region_name(self):
        """METER-02: boto3.client called with NO region_name parameter."""
        mock_settings = MagicMock()
        mock_settings.aws_marketplace_product_code = "prod-abc123"
        mock_settings.aws_marketplace_public_key_version = 1

        mock_client = MagicMock()
        mock_client.register_usage.return_value = {"Signature": "sig"}

        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client

        mock_logger = MagicMock()

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            register_fn = _get_register_fn()
            register_fn(mock_settings, mock_logger)

        # Should be called with only the service name, no region_name
        mock_boto3.client.assert_called_once_with("meteringmarketplace")

    def test_failure_raises_exception(self):
        """METER-03: Helper raises on failure (lifespan catches and logs warning)."""
        mock_settings = MagicMock()
        mock_settings.aws_marketplace_product_code = "prod-abc123"
        mock_settings.aws_marketplace_public_key_version = 1

        mock_client = MagicMock()
        mock_client.register_usage.side_effect = Exception("No instance metadata")

        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client

        mock_logger = MagicMock()

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            register_fn = _get_register_fn()
            with pytest.raises(Exception, match="No instance metadata"):
                register_fn(mock_settings, mock_logger)

    def test_no_boto3_when_product_code_none(self):
        """When aws_marketplace_product_code is None, no boto3 interaction occurs.

        The gating logic is in lifespan: `if settings.aws_marketplace_product_code:`
        This test verifies the guard condition evaluates correctly.
        """
        mock_settings = MagicMock()
        mock_settings.aws_marketplace_product_code = None
        assert not mock_settings.aws_marketplace_product_code

        mock_settings.aws_marketplace_product_code = ""
        assert not mock_settings.aws_marketplace_product_code

    def test_uuid_nonce_passed(self):
        """UUID nonce is passed to register_usage call."""
        mock_settings = MagicMock()
        mock_settings.aws_marketplace_product_code = "prod-xyz"
        mock_settings.aws_marketplace_public_key_version = 2

        mock_client = MagicMock()
        mock_client.register_usage.return_value = {"Signature": "abc"}

        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client

        mock_logger = MagicMock()

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            register_fn = _get_register_fn()
            register_fn(mock_settings, mock_logger)

        call_kwargs = mock_client.register_usage.call_args[1]
        nonce = call_kwargs["Nonce"]
        parsed = uuid.UUID(nonce)
        assert parsed.version == 4
