"""fix(#1746): the credential policy for basic and header-key service auth.

Covers the four additions to ``app/core/service_tokens.py`` and the two
invariants they carry. The first is that the composed credential is never
judged by ``HEADER_TOKEN_CHARSET``: the inputs are validated and the encoding
happens afterwards, so a base64 blob containing ``+`` or ``/`` is safe by
construction rather than by a second charset check. The second is that
``build_credential_header`` returns None for ArcGIS whatever the method,
because an ArcGIS token is percent-encoded into a URL query and a header
composed for it would put an Authorization line inside a query string.
"""

from __future__ import annotations

import base64
import string

import pytest

from app.core import service_tokens
from app.core.service_tokens import (
    BASIC_USERNAME_POLICY,
    CREDENTIAL_INPUT_POLICY,
    CREDENTIAL_METHOD_POLICY,
    HEADER_NAME_POLICY,
    HEADER_TOKEN_CHARSET,
    HEADER_TOKEN_MIN_LENGTH,
    HEADER_TOKEN_POLICY,
    RESERVED_HEADER_NAME_POLICY,
    RESERVED_HEADER_NAMES,
    CredentialMethod,
    ServiceCredential,
    build_credential_header,
    credential_header_line,
    credential_input_rejection_reason,
    header_name_rejection_reason,
    header_token_rejection_reason,
)

# A bearer token that satisfies the existing base64url policy, used wherever a
# test needs the bearer branch to succeed rather than to be the subject.
GOOD_BEARER = "abc.DEF-ghi_012="

# Formats whose credential travels as a header, and one that does not.
HEADER_FORMATS = ("wfs", "ogcapi_features")
ARCGIS_FORMAT = "arcgis_featureserver"


class TestCredentialInputRejection:
    """Usernames, passwords and header values: printable ASCII, no spaces."""

    @pytest.mark.parametrize(
        "value",
        [
            "plain-value",
            "a~b1234",
            "abc?",
            "x>y",
            "punctuation!#$%&'*+,-./:;<=>?@[]^_`{|}~",
            "".join(sorted(HEADER_TOKEN_CHARSET)),
            "9" * 200,
        ],
    )
    def test_printable_ascii_is_accepted(self, value: str) -> None:
        assert credential_input_rejection_reason(value) is None

    @pytest.mark.parametrize(
        ("value", "why"),
        [
            (None, "absent"),
            ("", "empty"),
            ("has space", "inner space"),
            (" leading", "leading space"),
            ("trailing ", "trailing space"),
            ("tab\there", "tab"),
            ("carriage\rreturn", "CR"),
            ("line\nfeed", "LF"),
            ("crlf\r\n", "CRLF"),
            ("vertical\x0btab", "vertical tab"),
            ("form\x0cfeed", "form feed"),
            ("nul\x00byte", "NUL"),
            ("delete\x7fchar", "DEL is not printable"),
            ("café-value", "non-ASCII letter"),
            ("nbsp\u00a0here", "non-ASCII whitespace"),
            ("emoji\U0001f600", "non-ASCII astral"),
            ("你好", "non-Latin script"),
        ],
    )
    def test_rejections(self, value: str | None, why: str) -> None:
        assert credential_input_rejection_reason(value) == CREDENTIAL_INPUT_POLICY, why

    def test_absent_is_a_rejection_unlike_the_bearer_rule(self) -> None:
        """The two functions differ on None on purpose.

        ``header_token_rejection_reason(None)`` means "no token supplied and
        none required". This one only ever judges a field the chosen method
        requires, so a missing one is a rejection.
        """
        assert header_token_rejection_reason(None) is None
        assert credential_input_rejection_reason(None) == CREDENTIAL_INPUT_POLICY


class TestHeaderNameRejection:
    """RFC 7230 token characters, and no name that is spoken for."""

    @pytest.mark.parametrize(
        "name",
        [
            # The five header names the surveyed providers actually use. A
            # field hardcoded to X-API-Key would serve exactly one of them.
            "X-API-Key",
            "key",
            "Ocp-Apim-Subscription-Key",
            "maxar-api-key",
            "authkey",
            "apikey",
            "X-Api-Key123",
            "!#$%&'*+-.^_`|~",
        ],
    )
    def test_token_characters_are_accepted(self, name: str) -> None:
        assert header_name_rejection_reason(name) is None

    @pytest.mark.parametrize(
        ("name", "why"),
        [
            (None, "absent"),
            ("", "empty"),
            ("X-API:Key", "colon"),
            ("X API Key", "space"),
            ("X-API-Key\r", "CR"),
            ("X-API-Key\n", "LF"),
            ("X-API-Key\t", "tab"),
            ("X-API=Key", "equals is not a token character"),
            ("X-API,Key", "comma"),
            ("X-API;Key", "semicolon"),
            ("X-API@Key", "at sign"),
            ("X-API(Key)", "parentheses"),
            ('X-API"Key"', "quote"),
            ("X-API/Key", "solidus"),
            ("X-Küy", "non-ASCII"),
        ],
    )
    def test_charset_rejections(self, name: str | None, why: str) -> None:
        assert header_name_rejection_reason(name) == HEADER_NAME_POLICY, why

    def test_the_denylist_is_the_two_groups_and_nothing_else(self) -> None:
        """Names GeoLens sets, and names that change the transport.

        fix(#1756 codex round 7): the second group was missing, so a caller
        could send ``Transfer-Encoding: chunked`` as their API key header and
        re-frame the request body, or ``Proxy-Authorization``, which a
        configured forward proxy reads rather than the service.
        """
        geolens_sets = {
            "authorization",
            "x-esri-authorization",
            "accept",
            "accept-encoding",
            "content-type",
            "content-length",
            "host",
            "cookie",
            "set-cookie",
            "user-agent",
            "referer",
        }
        changes_the_transport = {
            "transfer-encoding",
            "connection",
            "proxy-authorization",
            "proxy-connection",
            "keep-alive",
            "te",
            "trailer",
            "upgrade",
            "expect",
        }
        assert RESERVED_HEADER_NAMES == frozenset(geolens_sets | changes_the_transport)

    @pytest.mark.parametrize("reserved", sorted(RESERVED_HEADER_NAMES))
    @pytest.mark.parametrize("case", ["lower", "upper", "title", "mixed"])
    def test_reserved_names_are_refused_in_any_case(
        self, reserved: str, case: str
    ) -> None:
        spellings = {
            "lower": reserved,
            "upper": reserved.upper(),
            "title": reserved.title(),
            "mixed": "".join(
                character.upper() if index % 2 else character
                for index, character in enumerate(reserved)
            ),
        }
        assert (
            header_name_rejection_reason(spellings[case]) == RESERVED_HEADER_NAME_POLICY
        )

    def test_a_reserved_name_is_refused_for_the_reserved_reason(self) -> None:
        """Not merely refused: the message has to say which rule bit.

        A charset message for ``AUTHORIZATION`` would send the user hunting
        for an invalid character that is not there.
        """
        assert header_name_rejection_reason("AUTHORIZATION") != HEADER_NAME_POLICY

    def test_accept_encoding_is_refused(self) -> None:
        """fix(#1770 round 49 P2, `service_tokens.py` `RESERVED_HEADER_NAMES`).

        `service_endpoints.py::credential_headers` and `probe_bounds.py::
        bounded_probe_read` both build `{name: value, "Accept-Encoding":
        "identity"}` -- the caller's pair first, GeoLens's own encoding pin
        second -- so a credential named exactly this (any case) was silently
        overwritten by the literal `"identity"` before those in-process
        checks ever made the request, turning a credentialed capabilities
        read into an anonymous one. Counterfactual: remove `"accept-
        encoding"` from `RESERVED_HEADER_NAMES` and this returns `None`
        (accepted) instead of the reserved-name policy.
        """
        assert (
            header_name_rejection_reason("Accept-Encoding")
            == RESERVED_HEADER_NAME_POLICY
        )

    @pytest.mark.parametrize(
        "name", [":authority", ":method", ":Path", ":SCHEME", ":status"]
    )
    def test_pseudo_headers_are_refused_as_reserved(self, name: str) -> None:
        """fix(#1756 codex round 7): protocol framing, not a header field.

        The charset rule would refuse these anyway, for the colon. The reason
        matters: a caller told their colon is an invalid character will try
        again without it, and a caller told the name is spoken for will not.
        """
        assert header_name_rejection_reason(name) == RESERVED_HEADER_NAME_POLICY

    @pytest.mark.parametrize(
        "name",
        [
            "Transfer-Encoding",
            "Connection",
            "TE",
            "Trailer",
            "Upgrade",
            "Proxy-Authorization",
            "Proxy-Connection",
            "Keep-Alive",
            "Expect",
            "Set-Cookie",
        ],
    )
    def test_transport_headers_are_refused(self, name: str) -> None:
        """fix(#1756 codex round 7): these reframe the request, not its body.

        ``Transfer-Encoding: chunked`` is honoured by httpx and by the libcurl
        header file GDAL reads, and ``Proxy-Authorization`` is read by a
        configured forward proxy rather than by the service being addressed.
        Tried in the casing a user would actually type.
        """
        assert header_name_rejection_reason(name) == RESERVED_HEADER_NAME_POLICY
        assert header_name_rejection_reason(name.upper()) == RESERVED_HEADER_NAME_POLICY
        assert header_name_rejection_reason(name.lower()) == RESERVED_HEADER_NAME_POLICY


class TestBuildCredentialHeaderProducesTheHeader:
    @pytest.mark.parametrize("service_format", HEADER_FORMATS)
    def test_bearer(self, service_format: str) -> None:
        assert build_credential_header(
            ServiceCredential(
                method=CredentialMethod.BEARER,
                service_format=service_format,
                token=GOOD_BEARER,
            )
        ) == ("Authorization", f"Bearer {GOOD_BEARER}")

    @pytest.mark.parametrize(
        ("username", "secret", "expected"),
        [
            # The memo's two counterexamples. Both encode to something the
            # bearer charset would refuse or accept by accident, and both must
            # work, because the encoded form is never charset-checked.
            ("wfs", "a~b1234", "d2ZzOmF+YjEyMzQ="),
            ("admin", "abc?", "YWRtaW46YWJjPw=="),
            # `>`, `?` and `~` at an offset congruent to 2 mod 3, which is the
            # only way standard base64 emits `+` or `/`.
            ("wfs", "a>bcdef", "d2ZzOmE+YmNkZWY="),
            ("wfs", "a?bcdef", "d2ZzOmE/YmNkZWY="),
        ],
    )
    def test_basic_encodes_server_side(
        self, username: str, secret: str, expected: str
    ) -> None:
        assert build_credential_header(
            ServiceCredential(
                method=CredentialMethod.BASIC,
                service_format="wfs",
                username=username,
                password=secret,
            )
        ) == ("Authorization", f"Basic {expected}")
        assert base64.b64decode(expected).decode("ascii") == f"{username}:{secret}"

    def test_the_encoded_form_is_never_charset_checked(self) -> None:
        """The point of validating inputs and encoding afterwards.

        ``d2ZzOmF+YjEyMzQ=`` carries a ``+`` and ``d2ZzOmE/YmNkZWY=`` a ``/``,
        so both would be refused as bearer tokens. Whether they appear at all
        depends on the length of the username, which is why the rule cannot
        live on the encoded output.
        """
        for encoded in ("d2ZzOmF+YjEyMzQ=", "d2ZzOmE/YmNkZWY="):
            assert header_token_rejection_reason(encoded) == HEADER_TOKEN_POLICY
        # And the memo's second example encodes to something the charset would
        # have accepted, which is exactly why the difference is unexplainable
        # to a user and the check does not belong there.
        assert header_token_rejection_reason("YWRtaW46YWJjPw==") is None

    @pytest.mark.parametrize("service_format", HEADER_FORMATS)
    def test_header_key_passes_the_pair_through(self, service_format: str) -> None:
        assert build_credential_header(
            ServiceCredential(
                method=CredentialMethod.HEADER_KEY,
                service_format=service_format,
                header_name="Ocp-Apim-Subscription-Key",
                header_value="ab~cd?ef",
            )
        ) == ("Ocp-Apim-Subscription-Key", "ab~cd?ef")

    def test_the_method_enum_values_are_the_wire_literals(self) -> None:
        """Pinned because the request schema validates against these strings."""
        assert {member.value for member in CredentialMethod} == {
            "none",
            "bearer",
            "basic",
            "header",
        }
        assert CredentialMethod.HEADER_KEY.value == "header"


class TestBuildCredentialHeaderReturnsNone:
    @pytest.mark.parametrize(
        "auth",
        [
            None,
            ServiceCredential(),
            ServiceCredential(method=CredentialMethod.NONE, service_format="wfs"),
            ServiceCredential(method="none", service_format="ogcapi_features"),
        ],
        ids=["absent", "default", "explicit-none", "none-as-a-string"],
    )
    def test_no_credential(self, auth: ServiceCredential | None) -> None:
        assert build_credential_header(auth) is None

    @pytest.mark.parametrize("method", ["none", "basic", "header", "oauth"])
    def test_arcgis_gets_no_header_for_a_method_it_cannot_carry(
        self, method: str
    ) -> None:
        """feat(C2) narrowed D9's invariant from every method to three.

        Every field is populated, so nothing here returns None for want of an
        input. ArcGIS has no basic or named-API-key spelling at all, and the
        GDAL path still percent-encodes the bearer token into the source URL,
        so a header line composed for any of these would land inside a query
        string. The bearer case is the one that changed and is covered by
        ``test_arcgis_gets_a_bearer_header`` below.
        """
        assert (
            build_credential_header(
                ServiceCredential(
                    method=method,
                    service_format=ARCGIS_FORMAT,
                    token=GOOD_BEARER,
                    username="wfs",
                    password="a~b1234",
                    header_name="X-API-Key",
                    header_value="k1234567",
                )
            )
            is None
        )

    @pytest.mark.parametrize(
        "token",
        ["tok+slash/", "AA'#&ULTRASECRET", GOOD_BEARER, "a" * 3],
        ids=["reserved-chars", "url-reserved", "base64url", "shorter-than-the-floor"],
    )
    def test_arcgis_gets_a_bearer_header(self, token: str) -> None:
        """feat(C2), and the vocabulary difference that goes with it.

        An ArcGIS token is judged as a header VALUE (printable ASCII, no
        whitespace) rather than by ``HEADER_TOKEN_CHARSET``, so ``+``, ``/``
        and a token shorter than the WFS/OAPIF floor all compose. Those rules
        exist for a credential written into a file libcurl parses; an ArcGIS
        token never reaches that file, and refusing ``+`` would refuse
        legitimate ArcGIS tokens for a danger this path does not have.
        """
        assert build_credential_header(
            ServiceCredential(
                method=CredentialMethod.BEARER,
                service_format=ARCGIS_FORMAT,
                token=token,
            )
        ) == ("Authorization", f"Bearer {token}")

    @pytest.mark.parametrize("token", [None, "", "has space", "café"])
    def test_an_arcgis_token_that_cannot_be_a_header_value_is_refused(
        self, token: str | None
    ) -> None:
        """The floor the value charset still enforces: no whitespace, ASCII
        only. CR and LF are whitespace, so the header-smuggling class this
        rule exists for is closed on the ArcGIS path too."""
        with pytest.raises(ValueError):
            build_credential_header(
                ServiceCredential(
                    method=CredentialMethod.BEARER,
                    service_format=ARCGIS_FORMAT,
                    token=token,
                )
            )

    @pytest.mark.parametrize(
        "service_format", [None, "stac", "geojson", "shapefile", ""]
    )
    def test_a_format_whose_credential_is_not_a_header(
        self, service_format: str | None
    ) -> None:
        """An allowlist, so an unconsidered format degrades to no header.

        The resulting failure is a 401 from the origin, which is loud. The
        denylist version of this rule fails the other way.
        """
        assert (
            build_credential_header(
                ServiceCredential(
                    method=CredentialMethod.BEARER,
                    service_format=service_format,
                    token=GOOD_BEARER,
                )
            )
            is None
        )


class TestBuildCredentialHeaderRejections:
    @pytest.mark.parametrize(
        ("auth", "expected"),
        [
            (
                ServiceCredential(
                    method=CredentialMethod.BEARER, service_format="wfs", token="short"
                ),
                HEADER_TOKEN_POLICY,
            ),
            (
                ServiceCredential(
                    method=CredentialMethod.BEARER,
                    service_format="wfs",
                    token="has+plus+chars",
                ),
                HEADER_TOKEN_POLICY,
            ),
            (
                ServiceCredential(
                    method=CredentialMethod.BEARER, service_format="wfs", token=None
                ),
                HEADER_TOKEN_POLICY,
            ),
            (
                ServiceCredential(
                    method=CredentialMethod.BASIC,
                    service_format="wfs",
                    username="wfs",
                    password="carriage\rreturn",
                ),
                CREDENTIAL_INPUT_POLICY,
            ),
            (
                ServiceCredential(
                    method=CredentialMethod.BASIC,
                    service_format="wfs",
                    username="wfs",
                    password="line\nfeed",
                ),
                CREDENTIAL_INPUT_POLICY,
            ),
            (
                ServiceCredential(
                    method=CredentialMethod.BASIC,
                    service_format="wfs",
                    username="café",
                    password="a~b1234",
                ),
                CREDENTIAL_INPUT_POLICY,
            ),
            (
                ServiceCredential(
                    method=CredentialMethod.BASIC,
                    service_format="wfs",
                    username="wfs",
                    password=None,
                ),
                CREDENTIAL_INPUT_POLICY,
            ),
            (
                ServiceCredential(
                    method=CredentialMethod.BASIC,
                    service_format="wfs",
                    username="wfs",
                    password="",
                ),
                CREDENTIAL_INPUT_POLICY,
            ),
            (
                ServiceCredential(
                    method=CredentialMethod.BASIC,
                    service_format="wfs",
                    username="two:parts",
                    password="a~b1234",
                ),
                BASIC_USERNAME_POLICY,
            ),
            (
                ServiceCredential(
                    method=CredentialMethod.HEADER_KEY,
                    service_format="wfs",
                    header_name="X-API:Key",
                    header_value="k1234567",
                ),
                HEADER_NAME_POLICY,
            ),
            (
                ServiceCredential(
                    method=CredentialMethod.HEADER_KEY,
                    service_format="wfs",
                    header_name=None,
                    header_value="k1234567",
                ),
                HEADER_NAME_POLICY,
            ),
            (
                ServiceCredential(
                    method=CredentialMethod.HEADER_KEY,
                    service_format="wfs",
                    header_name="Authorization",
                    header_value="k1234567",
                ),
                RESERVED_HEADER_NAME_POLICY,
            ),
            (
                ServiceCredential(
                    method=CredentialMethod.HEADER_KEY,
                    service_format="wfs",
                    header_name="Transfer-Encoding",
                    header_value="chunked",
                ),
                RESERVED_HEADER_NAME_POLICY,
            ),
            (
                ServiceCredential(
                    method=CredentialMethod.HEADER_KEY,
                    service_format="wfs",
                    header_name=":authority",
                    header_value="k1234567",
                ),
                RESERVED_HEADER_NAME_POLICY,
            ),
            (
                ServiceCredential(
                    method=CredentialMethod.HEADER_KEY,
                    service_format="wfs",
                    header_name="X-API-Key",
                    header_value="kéy-value",
                ),
                CREDENTIAL_INPUT_POLICY,
            ),
            (
                ServiceCredential(
                    method=CredentialMethod.HEADER_KEY,
                    service_format="wfs",
                    header_name="X-API-Key",
                    header_value=None,
                ),
                CREDENTIAL_INPUT_POLICY,
            ),
            (
                ServiceCredential(method="oauth", service_format="wfs"),
                CREDENTIAL_METHOD_POLICY,
            ),
            (
                ServiceCredential(method="", service_format="wfs"),
                CREDENTIAL_METHOD_POLICY,
            ),
        ],
    )
    def test_raises_the_policy(self, auth: ServiceCredential, expected: str) -> None:
        with pytest.raises(ValueError) as raised:
            build_credential_header(auth)
        assert str(raised.value) == expected

    @pytest.mark.parametrize(
        "supplied",
        [
            "carriage\rreturn",
            "line\nfeed",
            "café-value",
            "has space",
        ],
    )
    def test_no_message_ever_echoes_the_input(self, supplied: str) -> None:
        """The message reaches a 422 body, a log line and a job row.

        Each value is tried in every position that can raise, so a branch that
        grew an interpolation is caught wherever it is. The values are the
        ones every branch refuses, which is what lets the count below be
        exact.
        """
        candidates = [
            ServiceCredential(
                method=CredentialMethod.BASIC,
                service_format="wfs",
                username=supplied,
                password="a~b1234",
            ),
            ServiceCredential(
                method=CredentialMethod.BASIC,
                service_format="wfs",
                username="wfs",
                password=supplied,
            ),
            ServiceCredential(
                method=CredentialMethod.HEADER_KEY,
                service_format="wfs",
                header_name=supplied,
                header_value="k1234567",
            ),
            ServiceCredential(
                method=CredentialMethod.HEADER_KEY,
                service_format="wfs",
                header_name="X-API-Key",
                header_value=supplied,
            ),
            ServiceCredential(
                method=CredentialMethod.BEARER,
                service_format="wfs",
                token=supplied,
            ),
        ]
        raised_count = 0
        for auth in candidates:
            try:
                build_credential_header(auth)
            except ValueError as exc:
                raised_count += 1
                assert supplied not in str(exc)
        # Positive control: an assertion inside a `try` that never raises
        # would pass while testing nothing.
        assert raised_count == len(candidates)

    def test_the_colon_rejection_does_not_echo_the_username(self) -> None:
        """The one value a password may hold and a username may not."""
        with pytest.raises(ValueError) as raised:
            build_credential_header(
                ServiceCredential(
                    method=CredentialMethod.BASIC,
                    service_format="wfs",
                    username="two:parts",
                    password="a~b1234",
                )
            )
        assert "two:parts" not in str(raised.value)
        # And a colon in the password is fine, since nothing has to split it.
        assert build_credential_header(
            ServiceCredential(
                method=CredentialMethod.BASIC,
                service_format="wfs",
                username="wfs",
                password="two:parts",
            )
        ) == ("Authorization", f"Basic {base64.b64encode(b'wfs:two:parts').decode()}")


class TestPolicyConstants:
    def test_no_policy_constant_can_interpolate(self) -> None:
        """Mirrors the pin at tests/test_service_refresh_1220.py on
        HEADER_TOKEN_POLICY, over every policy string in the module rather
        than the one that existed when that test was written."""
        policies = {
            name: value
            for name, value in vars(service_tokens).items()
            if name.endswith("_POLICY") and isinstance(value, str)
        }
        # Positive control on the collection itself: five new constants plus
        # the one that shipped before this lane.
        assert len(policies) >= 6, sorted(policies)
        for name, value in policies.items():
            assert "{" not in value, name
            assert "}" not in value, name
            assert "%s" not in value, name

    def test_every_policy_constant_is_reachable_from_a_rejection(self) -> None:
        """A message nothing can produce is copy nobody proofreads."""
        produced = {
            credential_input_rejection_reason(""),
            header_name_rejection_reason("bad name"),
            header_name_rejection_reason("Cookie"),
            header_token_rejection_reason("bad token"),
        }
        with pytest.raises(ValueError) as raised:
            build_credential_header(
                ServiceCredential(
                    method=CredentialMethod.BASIC,
                    service_format="wfs",
                    username="two:parts",
                    password="a~b1234",
                )
            )
        produced.add(str(raised.value))
        with pytest.raises(ValueError) as raised:
            build_credential_header(
                ServiceCredential(method="oauth", service_format="wfs")
            )
        produced.add(str(raised.value))
        assert produced == {
            CREDENTIAL_INPUT_POLICY,
            HEADER_NAME_POLICY,
            RESERVED_HEADER_NAME_POLICY,
            HEADER_TOKEN_POLICY,
            BASIC_USERNAME_POLICY,
            CREDENTIAL_METHOD_POLICY,
        }


class TestTheExistingBearerPolicyIsUntouched:
    """The standing constraint: HEADER_TOKEN_CHARSET is not widened."""

    def test_charset_and_floor_are_unchanged(self) -> None:
        assert HEADER_TOKEN_CHARSET == frozenset(
            string.ascii_letters + string.digits + "._-="
        )
        assert HEADER_TOKEN_MIN_LENGTH == 8

    def test_the_two_charsets_are_different_rules(self) -> None:
        """A value the credential rule accepts and the bearer rule refuses.

        If these two ever collapse into one, a basic password would have to
        satisfy the base64url alphabet, which is the failure this split
        exists to prevent.
        """
        assert credential_input_rejection_reason("a~b1234") is None
        assert header_token_rejection_reason("a~b1234") == HEADER_TOKEN_POLICY
        assert service_tokens.CREDENTIAL_INPUT_CHARSET > HEADER_TOKEN_CHARSET


class TestCredentialHeaderLine:
    def test_joins_with_a_colon_and_a_space(self) -> None:
        assert credential_header_line(("X-API-Key", "k1234567")) == (
            "X-API-Key: k1234567"
        )

    def test_is_exactly_one_line_with_no_trailing_newline(self) -> None:
        """Both writers append their own newline."""
        line = credential_header_line(("Authorization", "Basic d2ZzOmF+YjEyMzQ="))
        assert line.splitlines() == [line]
        assert not line.endswith("\n")

    def test_round_trips_the_builder_output(self) -> None:
        pair = build_credential_header(
            ServiceCredential(
                method=CredentialMethod.BASIC,
                service_format="wfs",
                username="wfs",
                password="a~b1234",
            )
        )
        assert pair is not None
        assert credential_header_line(pair) == ("Authorization: Basic d2ZzOmF+YjEyMzQ=")
