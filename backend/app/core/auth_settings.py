"""Sign-up and sign-in settings read from the environment.

Each field is the default of the persistent setting with the same key, and the
value in effect when ENV_ONLY_CONFIG is true.
"""

from pydantic import BaseModel, Field, field_validator

from app.platform.domain_validation import is_domain_pattern_valid, normalize_domains


class AuthSettings(BaseModel):
    registration_enabled: bool = False
    email_verification_required: bool = True
    password_login_enabled: bool = True
    login_rate_limit: int = Field(default=5, ge=1, le=1000)
    # Comma-separated; empty allows every domain.
    allowed_email_domains: str = ""

    @field_validator("allowed_email_domains", mode="after")
    @classmethod
    def validate_allowed_email_domains(cls, v: str) -> str:
        domains = normalize_domains(v.split(","))
        for pattern in domains:
            if not is_domain_pattern_valid(pattern):
                raise ValueError(
                    f"ALLOWED_EMAIL_DOMAINS has an invalid domain {pattern!r}; "
                    "use comma-separated domains such as example.com or "
                    "*.example.com"
                )
        return ",".join(domains)

    @property
    def allowed_email_domains_list(self) -> list[str]:
        return [domain for domain in self.allowed_email_domains.split(",") if domain]
