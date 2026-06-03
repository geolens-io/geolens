#!/usr/bin/env python3
"""GeoLens license tooling — vendor-side keygen and license minting.

This script is for the **vendor** (whoever sells GeoLens Enterprise). It is not
needed to run GeoLens.

  # 1. One-time: generate the signing keypair.
  python scripts/license_tool.py keygen --out-dir ./license-keys
  #   -> license-keys/license_private_key.pem   (SECRET — never commit/ship)
  #   -> license-keys/license_public_key.pem    (ship this with the product)

  # Bundle the PUBLIC key as the verifier trust root in the enterprise build.
  # It is read ONLY from this committed path (never an env var), so an operator
  # cannot swap in their own key:
  cp license-keys/license_public_key.pem backend/app/core/license_public_key.pem

  # 2. Per customer: mint a signed license token.
  python scripts/license_tool.py mint \
      --private-key license-keys/license_private_key.pem \
      --customer "Acme Water District" --days 365 --seats 250

The minted token is what a customer sets as GEOLENS_LICENSE_KEY. Verification is
offline (no phone-home) against the public key — see app/core/license.py.

SECURITY: anyone holding the private key can mint licenses. Keep it in a secrets
manager / HSM, not in the repo.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_ALGORITHM = "EdDSA"


def _cmd_keygen(args: argparse.Namespace) -> int:
    private_key = Ed25519PrivateKey.generate()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        priv_path = out / "license_private_key.pem"
        pub_path = out / "license_public_key.pem"
        priv_path.write_bytes(private_pem)
        priv_path.chmod(0o600)
        pub_path.write_bytes(public_pem)
        print(f"Wrote private key (SECRET): {priv_path}", file=sys.stderr)
        print(f"Wrote public key (ship this): {pub_path}", file=sys.stderr)
        print(
            "Keep the private key out of version control and in a secrets "
            "manager — anyone with it can mint licenses.",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(private_pem.decode())
        sys.stdout.write(public_pem.decode())
    return 0


def _cmd_mint(args: argparse.Namespace) -> int:
    private_pem = Path(args.private_key).read_bytes()
    key = serialization.load_pem_private_key(private_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        print("Private key is not an Ed25519 key.", file=sys.stderr)
        return 1

    now = datetime.now(UTC)
    claims: dict = {
        "edition": "enterprise",
        "iat": now,
        "exp": now + timedelta(days=args.days),
        "license_id": uuid.uuid4().hex,
    }
    if args.customer:
        claims["customer"] = args.customer
    if args.seats is not None:
        claims["seats"] = args.seats
    if args.features:
        claims["features"] = args.features
    if args.audience:
        # Binds the license to a deployment: the customer sets
        # GEOLENS_LICENSE_AUDIENCE to the same value so the token can't be
        # replayed on another instance.
        claims["aud"] = args.audience

    token = jwt.encode(claims, key, algorithm=_ALGORITHM)
    print(token)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="GeoLens license tooling (vendor-side)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    kg = sub.add_parser("keygen", help="Generate an Ed25519 signing keypair.")
    kg.add_argument(
        "--out-dir",
        help="Directory to write license_{private,public}_key.pem. "
        "If omitted, both PEMs are printed to stdout.",
    )
    kg.set_defaults(func=_cmd_keygen)

    mt = sub.add_parser("mint", help="Mint a signed enterprise license token.")
    mt.add_argument(
        "--private-key", required=True, help="Path to the Ed25519 private-key PEM."
    )
    mt.add_argument(
        "--customer", help="Customer name (stored as the `customer` claim)."
    )
    mt.add_argument(
        "--days", type=int, default=365, help="Validity in days (default 365)."
    )
    mt.add_argument("--seats", type=int, default=None, help="Optional seat cap.")
    mt.add_argument(
        "--features",
        nargs="*",
        default=None,
        help="Optional entitled feature/seam names.",
    )
    mt.add_argument(
        "--audience",
        help="Optional deployment id bound into the `aud` claim. The customer "
        "sets GEOLENS_LICENSE_AUDIENCE to the same value to enforce it.",
    )
    mt.set_defaults(func=_cmd_mint)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
