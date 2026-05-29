---
phase: 1137-sharing-and-embed-polish
reviewed: 2026-05-27T21:00:00Z
depth: deep
files_reviewed: 6
files_reviewed_list:
  - frontend/src/lib/builder/url-normalize.ts
  - frontend/src/components/builder/SharePanel.tsx
  - frontend/src/components/viewer/ViewerMap.tsx
  - frontend/src/pages/PublicViewerPage.tsx
  - backend/app/modules/embed_tokens/schemas.py
  - backend/app/modules/catalog/maps/router.py
findings:
  critical: 2
  warning: 3
  info: 2
  total: 7
status: issues_found
---

# Phase 1137: Code Review Report

**Reviewed:** 2026-05-27T21:00:00Z
**Depth:** deep
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Reviewed all six files introduced or modified by Phase 1137 (Sharing and Embed Polish).
The core sharing flow — sandbox hardening, CSP frame-ancestors emission, branding overlay,
Pitfall #6/#7 guards — is sound. Two blockers were found: (1) a backend/frontend canonical-form
divergence for IPv6 origins that produces invalid CSP directives and mismatches between the chip
label and the stored value; (2) a wildcard-subdomain bypass in the frontend normalizer that lets
`https://*.example.com` pass client-side validation before being rejected by the backend 422.
Three warnings cover a stale-closure rollback that silently discards concurrently-added chips, a
`configOrigins ?? []` reference-instability race that can wipe optimistic chip state mid-flight,
and dead state (`domainInput`/`parseOrigins`) that shadows the chip-input code path.

---

## Critical Issues

### CR-01: IPv6 canonical-form divergence produces invalid CSP directive

**File:** `backend/app/modules/embed_tokens/schemas.py:29` and `frontend/src/lib/builder/url-normalize.ts:72`

**Issue:** Python's `urlparse` strips square brackets from IPv6 addresses: `urlparse('http://[::1]:8080').hostname` returns `'::1'` (no brackets). `_normalize_origin` therefore stores `'http://::1:8080'`. The WHATWG `URL` constructor preserves brackets: `new URL('http://[::1]:8080').hostname` is `'[::1]'`, so `normalizeOrigin` returns `'http://[::1]:8080'`.

Consequences:
1. **Invalid CSP**: `_build_frame_ancestors` emits `frame-ancestors 'self' http://::1:8080`. The CSP spec (RFC 9116 / W3C CSP3 §2.6.1) requires IPv6 literals in source expressions to be enclosed in brackets. Browsers that follow the spec strictly will reject this directive and fall back to the default policy or ignore the entry entirely — the frame-ancestor restriction silently fails to apply.
2. **Chip/server mismatch**: The chip UI renders the frontend canonical form (`http://[::1]:8080`) but the server stores the backend form (`http://::1:8080`). After the first PATCH the server returns the stored (bracketless) form; the `configOrigins` sync effect then replaces the chip with the bracketless string, creating a visible flash of different text.

While IPv6 localhost is rare in production embeds, admin or staging environments commonly use it.

**Fix (backend — authoritative):** Reconstruct the host component using `parsed.netloc` (which preserves brackets) and strip the port manually, or use a bracket-aware reassembly:

```python
def _normalize_origin(origin: str) -> str:
    normalized = origin.strip().lower().rstrip("/")
    if "*" in normalized:
        raise ValueError("Wildcard origin not allowed")
    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"

    parsed = urlparse(normalized)
    if not parsed.hostname:
        raise ValueError(f"Invalid origin: {origin}")

    scheme = parsed.scheme or "https"
    # parsed.hostname strips brackets; use parsed.netloc to reconstruct host+port,
    # then re-parse port separately.
    host = parsed.hostname  # bare IP for non-IPv6; '::1' for IPv6
    # Determine bracket-safe host string for the output URL.
    # urlparse guarantees parsed.netloc contains the bracketed form for IPv6.
    # Extract it by stripping port from netloc.
    netloc_host = parsed.netloc.rsplit(":", 1)[0] if parsed.port else parsed.netloc
    # netloc_host is '[::1]' for IPv6, 'example.com' for DNS.
    port = parsed.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    if port:
        return f"{scheme}://{netloc_host}:{port}"
    return f"{scheme}://{netloc_host}"
```

**Fix (frontend — must match):** After normalization, check that the parsed hostname does not contain `*` (see CR-02) and reconstruct the IPv6 host with brackets using `parsed.hostname` directly (WHATWG already returns `[::1]`). The frontend is already correct; only the backend needs the fix. Add a parity test case:
```typescript
it("preserves IPv6 brackets: http://[::1]:8080 → http://[::1]:8080", () => {
  expect(normalizeOrigin('http://[::1]:8080')).toBe('http://[::1]:8080');
});
```

---

### CR-02: Frontend `normalizeOrigin` accepts wildcard-subdomain origins (`https://*.example.com`)

**File:** `frontend/src/lib/builder/url-normalize.ts:49`

**Issue:** The wildcard guard only catches inputs whose trimmed form starts with `*`:

```typescript
if (trimmed === '*' || trimmed.startsWith('*')) {
  throw new WildcardOriginError();
}
```

`'https://*.example.com'` does **not** start with `*`, so it passes the guard. The WHATWG `URL` constructor accepts `https://*.example.com` successfully (hostname is `*.example.com`). `normalizeOrigin` returns `'https://*.example.com'` — a wildcard origin — as if it were valid.

The backend `_normalize_origin` catches this because it checks `if "*" in normalized` **after** the full string has been lowercased, so the PATCH returns a 422 and the chip is rolled back. However:
- The chip is added to the optimistic UI for the duration of the network round-trip (typically 200–400 ms on LAN; longer remotely).
- The 422 error path at line 271 checks `/Wildcard/i.test(err.message)` and shows an origin error — but this is an after-the-fact recovery, not prevention.
- Any future code path that consumes `normalizeOrigin`'s return value before a server round-trip (e.g., local validation in a batch import) would pass the wildcard through unchecked.

The docstring at line 43 documents: _"throws WildcardOriginError if input is `*` or starts with `*`"_ — this specification is incomplete; it should cover all inputs whose parsed hostname contains `*`.

**Fix:**
```typescript
export function normalizeOrigin(input: string): string {
  const trimmed = input.trim();

  if (trimmed === '*' || trimmed.startsWith('*')) {
    throw new WildcardOriginError();
  }

  if (trimmed === '') {
    throw new InvalidOriginError(input);
  }

  const withScheme = trimmed.includes('://') ? trimmed : `https://${trimmed}`;

  let parsed: URL;
  try {
    parsed = new URL(withScheme);
  } catch {
    throw new InvalidOriginError(input);
  }

  if (!parsed.hostname) {
    throw new InvalidOriginError(input);
  }

  // Guard: wildcard anywhere in the parsed hostname (catches https://*.example.com)
  if (parsed.hostname.includes('*')) {
    throw new WildcardOriginError();
  }

  // ... rest unchanged
```

Add test:
```typescript
it("throws WildcardOriginError for https://*.example.com", () => {
  expect(() => normalizeOrigin('https://*.example.com')).toThrow(WildcardOriginError);
});
it("throws WildcardOriginError for https://sub.*.example.com", () => {
  expect(() => normalizeOrigin('https://sub.*.example.com')).toThrow(WildcardOriginError);
});
```

---

## Warnings

### WR-01: Stale-closure rollback in `handleAddOrigin` can discard concurrently-added chips

**File:** `frontend/src/components/builder/SharePanel.tsx:256–276`

**Issue:** `handleAddOrigin` captures `origins` (the current state value) at the time the closure is created during a render. The rollback at line 270 uses that closed-over value:

```typescript
async function handleAddOrigin(input: string) {
  // ...
  const newOrigins = [...origins, canonical];   // origins from render N
  setOrigins(newOrigins);                        // optimistic
  try {
    await updateEmbedToken.mutateAsync(...);
  } catch {
    setOrigins(origins);  // rollback to render-N snapshot, NOT current state
  }
}
```

If the user adds origin A (optimistic state: `[A]`), then — before the PATCH for A resolves — adds origin B (optimistic state: `[A, B]`):
- The PATCH for A fails.
- The rollback `setOrigins(origins)` uses the render-N snapshot: `[]`.
- State reverts to `[]`, silently discarding B even if B's PATCH is still in flight or has already succeeded.

The same pattern exists in `handleRemoveOrigin` at line 294 (`setOrigins(previous)`) using a `const previous = origins` snapshot — same race, different operation.

**Fix:** Use the functional form of `setState` for rollback so it operates on current state, not the snapshot:

```typescript
// handleAddOrigin: track the count added, not the pre-add snapshot
const addedCanonical = canonical; // capture what was added
try {
  await updateEmbedToken.mutateAsync(...);
} catch {
  // Remove what was optimistically added, regardless of subsequent adds
  setOrigins((current) => current.filter((o) => o !== addedCanonical));
  // ... show error
}

// handleRemoveOrigin: re-insert what was removed
const removedOrigin = target;
try {
  await updateEmbedToken.mutateAsync(...);
} catch {
  setOrigins((current) =>
    current.includes(removedOrigin) ? current : [...current, removedOrigin]
  );
  toast.error(t('share.updateFailed'));
}
```

---

### WR-02: `configOrigins ?? []` creates a new array reference on every render, causing the sync `useEffect` to fire continuously and wipe in-flight optimistic chip state

**File:** `frontend/src/components/builder/SharePanel.tsx:654` and `169–171`

**Issue:**

```typescript
// ShareDialog (parent), line 654:
const configOrigins = activeEmbedToken?.allowed_origins ?? [];

// ShareLinkSettings (child), lines 169–171:
useEffect(() => {
  setOrigins(configOrigins);
}, [configOrigins]);
```

When `activeEmbedToken` is defined but `allowed_origins` is `null` (no restrictions), `?? []` evaluates on every render to a **new** `[]` reference. React's `useEffect` compares deps by reference, so `[configOrigins]` changes every render, causing the effect to fire every render cycle and calling `setOrigins([])`.

The critical race window: a user types an origin and presses Enter. `handleAddOrigin` sets `origins = ['https://example.com']` optimistically and fires `updateEmbedToken.mutateAsync`. While the PATCH is in flight, `updateEmbedToken.isPending` flips to `true`, causing the parent `ShareDialog` to re-render (TanStack mutation state change). The re-render creates a new `configOrigins = []`, the `useEffect` fires, and `setOrigins([])` reverts the chip list — the user sees the chip disappear mid-flight. The chip returns only when the PATCH resolves and the query refetches.

This is a visible UX regression for the first origin added on any session where `allowed_origins` is currently `null`.

**Fix:** Stabilize `configOrigins` with `useMemo` in `ShareDialog`:

```typescript
// ShareDialog
const configOrigins = useMemo(
  () => activeEmbedToken?.allowed_origins ?? [],
  [activeEmbedToken?.allowed_origins]  // stable dep: same array ref when data unchanged
);
```

Or in `ShareLinkSettings`, guard the effect with a deep-equality check:

```typescript
const prevConfigOriginsRef = useRef<string[]>(configOrigins);
useEffect(() => {
  const prev = prevConfigOriginsRef.current;
  const same = prev.length === configOrigins.length &&
    prev.every((v, i) => v === configOrigins[i]);
  if (!same) {
    prevConfigOriginsRef.current = configOrigins;
    setOrigins(configOrigins);
  }
}, [configOrigins]);
```

---

### WR-03: `domainInput` state and `parseOrigins` function are dead code; embed tokens are always created with no origin restrictions from the share-link generation path

**File:** `frontend/src/components/builder/SharePanel.tsx:32–39, 636, 729, 768, 793`

**Issue:** `domainInput` is initialized to `''` (line 636) and reset to `''` on revoke (line 784). No rendered UI element calls `setDomainInput` — there is no input bound to this state in the current JSX. As a result, `parseOrigins(domainInput)` at lines 729, 768, and 793 always receives `''`.

`parseOrigins('')` returns `[]` (the empty-string element is filtered out by `filter(Boolean)`). This means `maybeCreateEmbedToken`, `handleRegenerateShareLink`, and `handleRegenerateEmbedToken` always call `createEmbedToken.mutateAsync({ mapId, allowedOrigins: undefined })` — the token is created with no origin restrictions regardless of what the user has configured in the chip input.

This is functionally correct (allowed origins can be added via `handleAddOrigin` after creation), but the dead state creates confusion about the intended initialization flow and could cause a regression if a future developer wires `domainInput` back without realizing `parseOrigins` bypasses `normalizeOrigin`.

**Fix:** Remove `domainInput`, `setDomainInput`, and `parseOrigins`. Replace the three call sites with a direct empty-origins call:

```typescript
// Before (line 729):
const origins = canUseAdvancedSharing ? parseOrigins(domainInput) : [];

// After:
// Allowed origins are managed via the chip input in ShareLinkSettings; no need to
// pass origins at creation time.
const tokenResult = await createEmbedToken.mutateAsync({ mapId });
```

---

## Info

### IN-01: `EmbedPreviewPane` constructs `src` URL via plain string concatenation instead of `URLSearchParams`, unlike `generateEmbedCode`

**File:** `frontend/src/components/builder/SharePanel.tsx:540`

**Issue:**

```typescript
// EmbedPreviewPane line 540 — plain concat:
const src = `${origin}/m/${shareToken}?embed=true&et=${embedTokenRaw}`;

// generateEmbedCode line 66–71 — URLSearchParams:
const params = new URLSearchParams({ embed: 'true' });
params.set('et', embedTokenRaw);
const url = `${origin}/m/${shareToken}?${params.toString()}`;
```

The current token format (`"et_" + secrets.token_urlsafe(32)`) uses only `[A-Za-z0-9_-]` characters, so the two forms produce identical output today. However if the token format ever gains characters that `URLSearchParams` would percent-encode (e.g., `=` padding or `+`), `EmbedPreviewPane` would silently produce a different URL than the copied embed code, causing the preview to load a different/broken URL than what the user pastes.

**Fix:** Use the same `generateEmbedCode` helper in `EmbedPreviewPane` to keep the two surfaces in sync:

```typescript
function EmbedPreviewPane({ shareToken, embedTokenRaw, origin }: EmbedPreviewPaneProps) {
  // ...
  const src = generateEmbedCode({ shareToken, embedTokenRaw, origin });
  // src is now the same string the user copies — preview and copy are always in sync
```

---

### IN-02: `showBranding` in `ViewerMap` can briefly flash the badge for enterprise users while `useBranding` is loading

**File:** `frontend/src/components/viewer/ViewerMap.tsx:149`

**Issue:**

```typescript
const showBranding = showInlineBranding && (!isEnterprise || branding?.show_badge !== false);
```

When `branding` is `undefined` (query not yet resolved), `branding?.show_badge` is `undefined`, and `undefined !== false` evaluates to `true`. An enterprise user with `show_badge: false` will therefore see the "Powered by GeoLens" overlay render briefly on mount before `useBranding` resolves and `show_badge: false` suppresses it.

`PublicViewerPage.tsx:47` has the identical issue for `showFooterBranding`:
```typescript
const showFooterBranding = !isEnterprise || branding?.show_badge !== false;
```

**Fix:** Default to hidden while loading:

```typescript
// ViewerMap.tsx line 149
const showBranding = showInlineBranding && (
  branding !== undefined &&   // wait for query to resolve
  (!isEnterprise || branding?.show_badge !== false)
);

// PublicViewerPage.tsx line 47
const showFooterBranding = branding !== undefined && (!isEnterprise || branding?.show_badge !== false);
```

---

_Reviewed: 2026-05-27T21:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
