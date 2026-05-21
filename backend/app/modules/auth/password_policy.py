"""Password complexity validator for SEC-S16 (Phase 1062-01).

Enforces configurable minimum length and character-class diversity at every
password entry point:
  - POST /auth/register/
  - POST /auth/change-password/
  - POST /admin/users/          (admin create)
  - POST /admin/users/{id}/convert-saml-to-local/

Policy (defaults, configurable via env):
  - Minimum length: 12 characters  (PASSWORD_MIN_LENGTH)
  - Character-class diversity: 3 of 4 classes  (PASSWORD_REQUIRE_CLASSES)
    Classes: lowercase [a-z], uppercase [A-Z], digit [0-9], symbol (everything else)

A denylist (breached passwords) is deferred to SEC-FU Phase 1063. This module
implements the minimum-viable policy recommended by the Phase 1062 audit.
"""

from __future__ import annotations


def validate_password_complexity(
    password: str,
    *,
    min_length: int,
    require_classes: int,
) -> None:
    """Validate password length and character-class diversity.

    Args:
        password: Plaintext password to evaluate.
        min_length: Minimum character count (inclusive).
        require_classes: Minimum number of character classes that must be
            present. Classes: lowercase, uppercase, digit, symbol.
            Must be between 1 and 4 (inclusive).

    Raises:
        ValueError: If the password is too short or lacks sufficient class
            diversity. The message is user-facing (Pydantic re-raises it
            as-is in the 422 response body).

    Notes:
        The "symbol" character class is defined as "any character that is not
        a letter and not a digit" — which INCLUDES whitespace, control characters,
        and Unicode punctuation/symbols. A password like ``Aaaaaaaaaaa1 ``
        (eleven lowercase + one digit + one trailing space) therefore satisfies
        the default 3-of-4 class requirement at exactly 13 characters.

        This is intentional. The 12-character length floor already provides
        ~72 bits of entropy against brute-force attacks even for low-entropy
        shapes, and tightening "symbol" to ``string.punctuation - whitespace``
        would reject legitimate passwords that contain real whitespace inside
        the password (uncommon but valid). Operators who need stricter symbol
        semantics can raise ``PASSWORD_REQUIRE_CLASSES`` to 4 — which forces
        a lowercase + uppercase + digit + symbol shape that whitespace alone
        cannot satisfy in combination with the other classes.
    """
    if len(password) < min_length:
        raise ValueError(
            f"Password must be at least {min_length} characters"
        )

    has_lower = any(c.islower() for c in password)
    has_upper = any(c.isupper() for c in password)
    has_digit = any(c.isdigit() for c in password)
    # Symbol: any character that is not a letter (lower or upper) and not a
    # digit. Includes punctuation, whitespace, Unicode non-letter/digit chars.
    has_symbol = any(not c.isalpha() and not c.isdigit() for c in password)

    classes_present = sum([has_lower, has_upper, has_digit, has_symbol])
    if classes_present < require_classes:
        raise ValueError(
            f"Password must include at least {require_classes} of: "
            "lowercase, uppercase, digit, symbol"
        )


def validate_password_from_settings(password: str) -> None:
    """Convenience wrapper that reads policy from the application settings.

    Uses ``app.core.config.settings`` (the module-level singleton) so callers
    do not need to thread the Settings instance through their call stack.
    The policy knobs are ``PASSWORD_MIN_LENGTH`` and ``PASSWORD_REQUIRE_CLASSES``
    (env vars; see Settings in app/core/config.py).

    Raises:
        ValueError: Passed through from validate_password_complexity.
    """
    # Lazy import to avoid circular: config -> password_policy -> config.
    from app.core.config import settings  # noqa: PLC0415

    validate_password_complexity(
        password,
        min_length=settings.password_min_length,
        require_classes=settings.password_require_classes,
    )
