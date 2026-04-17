"""AWS Marketplace RegisterUsage integration for container product billing."""

import uuid


def register_marketplace_usage(settings, logger) -> None:
    """Call RegisterUsage for AWS Marketplace hourly billing.

    This is a one-time startup call that activates metering; AWS handles
    continuous hourly billing thereafter. Non-fatal on failure (caller
    should catch exceptions).

    Args:
        settings: App settings with aws_marketplace_product_code and
                  aws_marketplace_public_key_version fields.
        logger: Structlog logger instance.
    """
    import boto3

    client = boto3.client("meteringmarketplace")  # No region_name -- auto-detected
    resp = client.register_usage(
        ProductCode=settings.aws_marketplace_product_code,
        PublicKeyVersion=settings.aws_marketplace_public_key_version,
        Nonce=str(uuid.uuid4()),
    )
    logger.info(
        "AWS Marketplace metering registered",
        product_code=settings.aws_marketplace_product_code,
        signature=resp.get("Signature", "")[:32] + "...",
    )
