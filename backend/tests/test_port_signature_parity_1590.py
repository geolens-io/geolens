"""Structural signature-parity sweep for #1590.

Default* implementations of the extension registry's Protocols are meant to
be drop-in replacements: an overlay swaps one in under the same registry key,
and any keyword-forwarding caller (the port's own in-tree callers, or a
future overlay that wraps a default and forwards by name) should see exactly
the call surface the Protocol promises. A default that renames a parameter,
reorders a positional one, or widens the signature to a bare ``**kwargs``,
breaks that promise silently — ``runtime_checkable`` only verifies attribute
PRESENCE (PEP 544), not signatures, so nothing catches the drift until a
positional or keyword caller hits a TypeError, or worse, a silently swapped
argument, deep in a forwarding chain.

This walks every Protocol the registry actually ships a default for — the
same 16-class set ``app.platform.extensions.defaults.__all__`` carries (see
``test_extensions.py::test_pre_pr_wildcard_surface_is_intact``, and
``test_pair_map_covers_every_default_the_facade_exports`` below, which pins
the pair map against that same ``__all__`` so a newly added default cannot
go unswept by omission) — paired with each one's Protocol, and asserts:

- every Protocol parameter exists on the default with the same NAME and KIND;
- the ORDERED sequence of POSITIONAL_ONLY/POSITIONAL_OR_KEYWORD parameter
  names matches, because name+kind alone would not catch two positional
  parameters swapping places (same names, same kinds, wrong order: every
  positional caller's arguments land in the other slot);
- when a Protocol parameter has a default, the implementation's corresponding
  parameter has one too (a caller relying on the Protocol's declared
  optionality shouldn't have to learn the default made it required).

A bare ``**kwargs`` shim fails the first check immediately (VAR_KEYWORD is a
different parameter KIND than the KEYWORD_ONLY parameters it stands in for),
which is exactly the shape of drift #1590 found.

A default MAY carry additional parameters the Protocol does not declare, but
only in the narrow shape that keeps them non-breaking: KEYWORD_ONLY, with a
default value (never a bare ``**kwargs``/``*args`` catch-all, never a
required extra). Adding a REQUIRED Protocol parameter is a signature change
that needs an EXTENSION_API_VERSION bump (version.py's 2 -> 3 precedent); an
optional superset on the DEFAULT alone does not, because an overlay that
never heard of the extra keyword is unaffected. Today's two instances,
``DefaultCatalogPort.finalize_presigned_object`` and
``.verify_completed_presigned_upload``'s ``replacing_dataset_id``, are
deliberate (see the comments on ``CatalogPort.finalize_presigned_object`` and
``.verify_completed_presigned_upload`` in ``core/catalog_port.py``) and
pinned below via ``EXPECTED_SUPERSET_PARAMS`` so a *new* undocumented
superset still fails loud instead of passing silently.
"""

from __future__ import annotations

import inspect

#: "{DefaultLabel}.{method}: +{param_name}" for every extra KEYWORD_ONLY,
#: defaulted parameter a default implementation is known to carry beyond
#: its Protocol. Anything found during the sweep that is not listed here is
#: treated as drift, not a superset — update this list (and confirm the
#: addition is deliberate) rather than widening the sweep's tolerance.
EXPECTED_SUPERSET_PARAMS = [
    "DefaultCatalogPort.finalize_presigned_object: +replacing_dataset_id",
    "DefaultCatalogPort.verify_completed_presigned_upload: +replacing_dataset_id",
]

_POSITIONAL_KINDS = (
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD,
)


def _protocol_member_names(protocol_cls: type) -> list[str]:
    """Names declared directly on the Protocol body — not typing's own machinery.

    ``vars(protocol_cls)`` holds only what the class body defines, so this
    naturally excludes inherited Protocol/Generic/object internals without an
    explicit denylist. Typing still stamps sunder attributes like
    ``_is_protocol`` on the class itself; every one of those starts with
    ``_``, and no real Protocol member in this codebase does, so filtering the
    leading underscore is sufficient.
    """
    names = []
    for name, value in vars(protocol_cls).items():
        if name.startswith("_"):
            continue
        if callable(value) or isinstance(value, property):
            names.append(name)
    return sorted(names)


def _member_params(owner_cls: type, name: str) -> list[inspect.Parameter]:
    """Every parameter of ``owner_cls``'s member ``name`` except ``self``.

    Unwraps ``@property`` to its getter, since ``CatalogPort`` declares
    ``priority_queue_threshold_bytes`` that way.
    """
    value = getattr(owner_cls, name)
    if isinstance(value, property):
        value = value.fget
    sig = inspect.signature(value)
    return [p for p in sig.parameters.values() if p.name != "self"]


def _protocol_default_pairs() -> list[tuple[type, type, str]]:
    """(Protocol, default class, label) for every Default* the registry publishes.

    Pairs the 16-class set ``test_pre_pr_wildcard_surface_is_intact`` already
    treats as "every Default* the facade exports" with each one's Protocol.
    ``AIProviderExtension`` appears twice (Anthropic + OpenAI-compatible are
    two named entries in the same ``ai_providers`` dispatch dict).
    """
    from app.core.catalog_port import CatalogPort
    from app.core.identity import IdentityExtension
    from app.core.processing_port import ProcessingPort
    from app.platform.extensions.defaults import (
        DefaultAnthropicProvider,
        DefaultAuditSink,
        DefaultAuthExtension,
        DefaultBillingExtension,
        DefaultBrandingExtension,
        DefaultCatalogPort,
        DefaultConnectorExtension,
        DefaultDataServingExtension,
        DefaultEntitlementPort,
        DefaultIdentityExtension,
        DefaultNotificationSink,
        DefaultOpenAICompatibleProvider,
        DefaultOpenAIEmbeddingProvider,
        DefaultPermissionExtension,
        DefaultProcessingPort,
        DefaultWorkflowExtension,
    )
    from app.platform.extensions.protocols import (
        AIProviderExtension,
        AuditSink,
        AuthExtension,
        BillingExtension,
        BrandingExtension,
        ConnectorExtension,
        DataServingExtension,
        EmbeddingProviderExtension,
        EntitlementPort,
        NotificationSink,
        PermissionExtension,
        WorkflowExtension,
    )

    return [
        (CatalogPort, DefaultCatalogPort, "DefaultCatalogPort"),
        (ProcessingPort, DefaultProcessingPort, "DefaultProcessingPort"),
        (IdentityExtension, DefaultIdentityExtension, "DefaultIdentityExtension"),
        (BrandingExtension, DefaultBrandingExtension, "DefaultBrandingExtension"),
        (AuthExtension, DefaultAuthExtension, "DefaultAuthExtension"),
        (AuditSink, DefaultAuditSink, "DefaultAuditSink"),
        (BillingExtension, DefaultBillingExtension, "DefaultBillingExtension"),
        (ConnectorExtension, DefaultConnectorExtension, "DefaultConnectorExtension"),
        (
            DataServingExtension,
            DefaultDataServingExtension,
            "DefaultDataServingExtension",
        ),
        (EntitlementPort, DefaultEntitlementPort, "DefaultEntitlementPort"),
        (NotificationSink, DefaultNotificationSink, "DefaultNotificationSink"),
        (
            PermissionExtension,
            DefaultPermissionExtension,
            "DefaultPermissionExtension",
        ),
        (WorkflowExtension, DefaultWorkflowExtension, "DefaultWorkflowExtension"),
        (AIProviderExtension, DefaultAnthropicProvider, "DefaultAnthropicProvider"),
        (
            AIProviderExtension,
            DefaultOpenAICompatibleProvider,
            "DefaultOpenAICompatibleProvider",
        ),
        (
            EmbeddingProviderExtension,
            DefaultOpenAIEmbeddingProvider,
            "DefaultOpenAIEmbeddingProvider",
        ),
    ]


def test_pair_map_covers_every_default_the_facade_exports() -> None:
    """The pair map must fail toward REPORTING an unpaired default, not toward silence.

    fix(#1590 review): a hand-written list of (Protocol, default) pairs only
    catches drift in whatever it already knows to check. A new Default*
    class added to the registry facade without a matching entry in
    ``_protocol_default_pairs()`` would sweep clean by omission, not by
    conformance — the signature test below would simply never look at it.
    This pins the pair map's label set against
    ``app.platform.extensions.defaults.__all__`` (the same facade surface
    ``test_pre_pr_wildcard_surface_is_intact`` treats as canonical), so an
    unpaired default fails loud here instead of silently going unchecked.
    """
    from app.platform.extensions import defaults as defaults_facade

    facade_default_names = {
        name for name in defaults_facade.__all__ if name.startswith("Default")
    }
    paired_labels = {label for _, _, label in _protocol_default_pairs()}

    missing = facade_default_names - paired_labels
    assert not missing, (
        "These Default* classes are exported by the registry facade "
        "(app.platform.extensions.defaults.__all__) but have no "
        "(Protocol, default) pairing in _protocol_default_pairs() — add one "
        "so the signature sweep actually covers them instead of skipping "
        f"them by omission: {sorted(missing)}"
    )


def test_default_implementations_match_their_protocol_signatures() -> None:
    """Every default's methods must accept exactly what its Protocol promises.

    fix(#1590): four default methods had drifted from their Protocol — a
    renamed parameter pair (``compute_schema_diff``) and three bare
    ``**kwargs`` shims (the presigned-upload trio) that only failed once a
    keyword caller or a forwarding overlay hit the gap. The same sweep also
    caught the identical ``**kwargs`` shape on
    ``DefaultAnthropicProvider``/``DefaultOpenAICompatibleProvider``'s
    ``stream``/``stream_chat_events``, not named in #1590 but the same bug.

    This is the general form of that check: it catches the same class of
    drift anywhere in the registry, not just the sites found by hand. A
    future ``**kwargs`` shim fails it immediately (VAR_KEYWORD is a
    different parameter KIND than the KEYWORD_ONLY parameters it stands in
    for), and so does a rename, a dropped parameter, a positional reorder
    that keeps the same names, or a default silently becoming required.
    """
    mismatches: list[str] = []
    superset_params: list[str] = []

    for protocol_cls, default_cls, label in _protocol_default_pairs():
        for name in _protocol_member_names(protocol_cls):
            if not hasattr(default_cls, name):
                mismatches.append(f"{label}.{name}: missing entirely")
                continue

            protocol_params = _member_params(protocol_cls, name)
            default_params = _member_params(default_cls, name)
            default_by_name = {p.name: p for p in default_params}

            for pp in protocol_params:
                dp = default_by_name.get(pp.name)
                if dp is None or dp.kind != pp.kind:
                    mismatches.append(
                        f"{label}.{name}: Protocol parameter {pp.name!r} "
                        f"({pp.kind.name}) is missing or has a different "
                        f"kind on the default (default params: "
                        f"{[(d.name, d.kind.name) for d in default_params]})"
                    )
                    continue
                if (
                    pp.default is not inspect.Parameter.empty
                    and dp.default is inspect.Parameter.empty
                ):
                    mismatches.append(
                        f"{label}.{name}: Protocol parameter {pp.name!r} has "
                        f"a default ({pp.default!r}) but the default "
                        "implementation's does not — a caller relying on "
                        "the Protocol's optionality would have to start "
                        "passing it explicitly"
                    )

            # Name+kind matching alone would miss two positional parameters
            # swapping places (e.g. old_feature_count/new_feature_count
            # trading positions): both still resolve by name, but every
            # positional caller's arguments would land in the other slot.
            protocol_positional = [
                pp.name for pp in protocol_params if pp.kind in _POSITIONAL_KINDS
            ]
            default_positional = [
                dp.name for dp in default_params if dp.kind in _POSITIONAL_KINDS
            ]
            if protocol_positional != default_positional:
                mismatches.append(
                    f"{label}.{name}: positional parameter ORDER differs "
                    f"(protocol={protocol_positional}, "
                    f"default={default_positional}) — a positional caller "
                    "binds by position, so even a same-name-set swap "
                    "changes which value lands where"
                )

            protocol_names = {pp.name for pp in protocol_params}
            for dp in default_params:
                if dp.name in protocol_names:
                    continue
                # An unnamed catch-all is exactly the shim #1590 found — it
                # is never a legitimate superset, no matter what it's called.
                if dp.kind in (
                    inspect.Parameter.VAR_KEYWORD,
                    inspect.Parameter.VAR_POSITIONAL,
                ):
                    mismatches.append(
                        f"{label}.{name}: default accepts a {dp.kind.name} "
                        f"catch-all ({dp.name!r}) the Protocol does not "
                        "declare — a **kwargs/*args shim, not a superset"
                    )
                elif (
                    dp.kind != inspect.Parameter.KEYWORD_ONLY
                    or dp.default is inspect.Parameter.empty
                ):
                    mismatches.append(
                        f"{label}.{name}: default has an extra parameter "
                        f"{dp.name!r} ({dp.kind.name}, "
                        f"default={'<required>' if dp.default is inspect.Parameter.empty else dp.default!r}) "
                        "that is not a keyword-only parameter with a default "
                        "— not a valid superset shape"
                    )
                else:
                    superset_params.append(f"{label}.{name}: +{dp.name}")

    assert not mismatches, (
        "Default implementation(s) drifted from their Protocol's parameters "
        "(names, kinds, positional order, and optionality must match; "
        "annotations and default VALUES are excluded). A default MAY carry "
        "extra KEYWORD_ONLY parameters that have defaults — nothing else:\n\n"
        + "\n".join(mismatches)
    )

    assert sorted(superset_params) == sorted(EXPECTED_SUPERSET_PARAMS), (
        "A default implementation gained or lost an undocumented superset "
        "parameter (a keyword-only parameter with a default that its "
        "Protocol does not declare). If this is deliberate, update "
        "EXPECTED_SUPERSET_PARAMS in this file — and if the new parameter "
        "should really be REQUIRED, it belongs on the Protocol behind an "
        "EXTENSION_API_VERSION bump instead (see core/catalog_port.py's "
        "#1590 comment on finalize_presigned_object for the precedent).\n"
        f"  found:    {sorted(superset_params)}\n"
        f"  expected: {sorted(EXPECTED_SUPERSET_PARAMS)}"
    )
