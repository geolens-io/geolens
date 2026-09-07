"""Password complexity validator for SEC-S16 (Phase 1062-01).

Enforces configurable minimum length and character-class diversity at every
password entry point:
  - POST /auth/register/
  - POST /auth/change-password/
  - POST /admin/users/          (admin create)
  - POST /admin/users/{id}/convert-saml-to-local/
  - POST /admin/users/{id}/reset-password/   (feat(#1715), admin reset)

Policy (defaults, configurable via env):
  - Minimum length: 12 characters  (PASSWORD_MIN_LENGTH)
  - Character-class diversity: 3 of 4 classes  (PASSWORD_REQUIRE_CLASSES)
    Classes: lowercase [a-z], uppercase [A-Z], digit [0-9], symbol (everything else)
  - Maximum 72 bytes once UTF-8 encoded (bcrypt's input limit; not configurable)

A denylist (breached passwords) is deferred to SEC-FU Phase 1063.
"""

from __future__ import annotations

# fix(#1715): bcrypt hashes at most 72 bytes, and pwdlib's
# BcryptHasher raises ValueError rather than truncating. Every entry point
# above accepts up to 256 characters, so enforcing this here (before
# hashing) gives one refusal shape instead of an unhandled 500/409 downstream.
#
# Not configurable: it's a property of the hash function, not a policy knob.
BCRYPT_MAX_PASSWORD_BYTES = 72


def validate_password_complexity(
    password: str,
    *,
    min_length: int,
    require_classes: int,
) -> None:
    """Validate password length and character-class diversity.

    Raises ValueError if too short, too long once UTF-8 encoded (bcrypt's
    72-byte limit), or lacking sufficient class diversity — the message is
    user-facing (Pydantic re-raises it as-is in the 422 body).

    The "symbol" class is "not a letter and not a digit", which INCLUDES
    whitespace and Unicode punctuation/symbols — a password like
    ``Aaaaaaaaaaa1 `` (11 lowercase + 1 digit + trailing space) satisfies
    the default 3-of-4 requirement at exactly 13 characters. Intentional:
    the 12-char floor already gives ~72 bits of entropy, and excluding
    whitespace from "symbol" would reject legitimate passwords containing
    it. Operators wanting stricter semantics can raise
    ``PASSWORD_REQUIRE_CLASSES`` to 4.
    """
    if len(password) < min_length:
        raise ValueError(f"Password must be at least {min_length} characters")

    # Checked before class diversity so a long multibyte password is told the
    # real reason rather than a class-diversity message it may also trip.
    encoded_length = len(password.encode("utf-8"))
    if encoded_length > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes when "
            f"encoded as UTF-8 (this one is {encoded_length}); accented, "
            "non-Latin and emoji characters each count as more than one byte"
        )

    has_lower = any(c.islower() for c in password)
    has_upper = any(c.isupper() for c in password)
    has_digit = any(c.isdigit() for c in password)
    # Symbol class defined in the docstring above.
    has_symbol = any(not c.isalpha() and not c.isdigit() for c in password)

    classes_present = sum([has_lower, has_upper, has_digit, has_symbol])
    if classes_present < require_classes:
        raise ValueError(
            f"Password must include at least {require_classes} of: "
            "lowercase, uppercase, digit, symbol"
        )


def validate_password_from_settings(password: str) -> None:
    """Convenience wrapper that reads policy from the application settings.

    Uses ``app.core.config.settings`` (module-level singleton) so callers
    don't need to thread the Settings instance through their call stack.
    Policy knobs: ``PASSWORD_MIN_LENGTH``, ``PASSWORD_REQUIRE_CLASSES``.
    """
    # Lazy import to avoid circular: config -> password_policy -> config.
    from app.core.config import settings  # noqa: PLC0415

    validate_password_complexity(
        password,
        min_length=settings.password_min_length,
        require_classes=settings.password_require_classes,
    )
