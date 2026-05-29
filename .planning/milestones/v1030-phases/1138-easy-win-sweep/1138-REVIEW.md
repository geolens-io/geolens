---
phase: 1138-easy-win-sweep
reviewed: 2026-05-28T00:00:00Z
depth: deep
files_reviewed: 8
files_reviewed_list:
  - frontend/src/lib/popup-rich-text.ts
  - frontend/src/components/map/FeaturePopup.tsx
  - frontend/src/components/builder/PopupConfigEditor.tsx
  - frontend/src/components/builder/hooks/use-builder-save.ts
  - frontend/src/components/builder/hooks/use-filtered-feature-count.ts
  - frontend/src/components/builder/LayerFilterEditor.tsx
  - frontend/src/components/builder/LayerEditorPanel.tsx
  - frontend/src/pages/MapBuilderPage.tsx
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: issues_found
---

# Phase 1138: Code Review Report

**Reviewed:** 2026-05-28
**Depth:** deep
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Phase 1138 ships three EASY features: Cmd/Ctrl+S keyboard shortcut, popup URL/media
rich-text rendering, and a "0 features after filter" empty-state hint. The XSS gate
analysis was the highest-priority task; the verdict is that the primary defense (scheme
restriction via URL_RE, no dangerouslySetInnerHTML anywhere) is sound and no exploit path
was found. The iframe `allow-same-origin + allow-scripts` combination on the YouTube embed
is safe because the src is always cross-origin to the GeoLens app.

Three correctness bugs were found. None are security-exploitable but two can silently
produce broken UI in real-world data:

1. `URL_RE` consumes trailing punctuation (`.`, `,`, `)`, `!`) into matched URL tokens,
   producing broken `<a href>` targets when feature attribute text contains prose URLs.
2. The same trailing-punctuation issue prevents `IMAGE_EXTS` / `VIDEO_EXTS` from matching
   in the standalone-URL branch, causing an image or video URL ending in `.` or `,` to
   render as a plain anchor instead of an inline embed.
3. The `useFilteredFeatureCount` effect depends on the entire `layer` object, causing the
   effect to re-run (and call `queryRenderedFeatures` synchronously) on every field change —
   including opacity slider drags at ~60 fps.

---

## Warnings

### WR-01: URL_RE consumes trailing punctuation — broken links and missed media embeds

**File:** `frontend/src/lib/popup-rich-text.ts:25`

**Issue:** The regex `URL_RE = /https?:\/\/[^\s<>"']+/gi` matches any non-whitespace,
non-quote character after the scheme. Common punctuation that ends a sentence or
parenthetical — `.`, `,`, `)`, `!` — is consumed into the matched token.

Demonstrated output for `'See https://example.com, for details'`:

```
{ kind: 'url', value: 'https://example.com,' }
```

Two consequences:

**A.** In the mixed-text branch (`splitTextWithUrls`), the rendered anchor becomes
`<a href="https://example.com,">https://example.com,</a>`. The trailing `,` is an
invalid URL; browsers typically fail or misroute the navigation.

**B.** In the standalone-URL branch (`isUrl()` → `classifyUrl()`), when a feature
property value is `'https://example.com/img.jpg.'`, `IMAGE_EXTS` anchors at `$` and the
trailing `.` causes it to miss, so the URL is classified as `'other'` (plain anchor)
instead of `'image'` (inline embed). The user sees a link instead of the image they
configured.

**Fix:** Strip trailing punctuation after matching. The standard approach used by
GitHub, Slack, and CommonMark is to remove trailing `).,;:!?` from each match if the
URL does not contain a balancing opening character for `)`:

```typescript
const URL_RE_RAW = /https?:\/\/[^\s<>"']+/gi;

function trimTrailingPunctuation(url: string): string {
  // Strip trailing sentence-ending characters that are almost never part of a URL.
  // Parentheses: only strip trailing ) if there is no matching ( in the URL.
  return url.replace(/[.,;:!?'")\]]+$/, (suffix) => {
    // Keep ) if there is a matching ( in the URL body
    const hasOpenParen = url.slice(0, url.length - suffix.length).includes('(');
    return hasOpenParen ? suffix : '';
  });
}
```

Then in `splitTextWithUrls` and `detectUrls`, apply `trimTrailingPunctuation` to
each match before emitting it as a URL segment.

---

### WR-02: `useFilteredFeatureCount` — redundant `layer` object in deps causes synchronous `queryRenderedFeatures` on every layer mutation

**File:** `frontend/src/components/builder/hooks/use-filtered-feature-count.ts:69`

**Issue:** The `useEffect` dependency array is `[map, layer?.id, layer?.filter, layer]`.
The trailing `layer` entry is the full `MapLayerResponse` object. Because
`MapLayerResponse` objects are recreated by `dispatchLayerAction` for every mutation
(opacity slider, visibility toggle, paint change, etc.), the effect fires on every such
mutation.

The effect body calls `recompute()` synchronously, which calls
`map.queryRenderedFeatures(undefined, { layers: [layer.id] })`. During an opacity
slider drag at ~60 fps, this is `queryRenderedFeatures` called ~60 times per second.
Per MapLibre docs, `queryRenderedFeatures` traverses all rendered tile data; it is not
free. At minimum this causes unnecessary event listener churn (`off('idle')` /
`on('idle')` at 60 fps).

The meaningful deps are already enumerated by `layer?.id` and `layer?.filter`. The
trailing `layer` object is entirely redundant.

**Fix:**

```typescript
// Before:
}, [map, layer?.id, layer?.filter, layer]);

// After:
}, [map, layer?.id, layer?.filter]);
```

The closure over `layer` inside `recompute` will still see the current layer value
because the effect re-runs whenever `layer?.id` or `layer?.filter` changes, which are
the only conditions that require a recount. Opacity / paint / visibility changes do not
affect feature count.

---

### WR-03: `<img>` in `ValueDisplay` renders SVG without `crossOrigin="anonymous"` — CORS credentialed request leaks Referer and may send cookies to the image host

**File:** `frontend/src/components/map/FeaturePopup.tsx:268-273`

**Issue:** The `<img>` element that renders classified image URLs has no
`crossOrigin="anonymous"` attribute:

```tsx
<img
  src={srcUrl}
  alt={srcUrl}
  loading="lazy"
  decoding="async"
  className="max-h-32 max-w-full rounded object-contain"
/>
```

`IMAGE_EXTS` matches `.svg` in addition to bitmap formats. An SVG URL sourced from a
feature property (user-controlled dataset content) causes the browser to issue a
credentialed request without `crossOrigin="anonymous"`. This means:

- The browser sends `Referer` (the builder URL) to the image host.
- In environments where `SameSite=None` cookies exist, credentials may accompany the
  request.

More importantly, SVG files loaded via `<img>` can reference external images and CSS
inside the SVG document, causing additional HTTP requests to attacker-controlled hosts.
Scripts in SVG `<img>` are sandboxed by modern browsers (no XSS risk), but tracking
pixels and URL-exfiltration via CSS `background-image` or `<image>` inside the SVG are
real risks against feature data sourced from untrusted sources.

Adding `crossOrigin="anonymous"` forces the request without credentials, preventing
cookie leakage. It also enables CORS-caching benefits and is the correct attribute for
externally-hosted images in a map context.

**Fix:**

```tsx
<img
  src={srcUrl}
  alt={srcUrl}
  loading="lazy"
  decoding="async"
  crossOrigin="anonymous"
  className="max-h-32 max-w-full rounded object-contain"
/>
```

Note: this will break display of same-origin images that are not served with
`Access-Control-Allow-Origin` headers. For this use case (feature attribute values that
are external URLs), all images are expected to be cross-origin and publicly accessible;
the CORS attribute is correct.

---

## Info

### IN-01: `YT_HOSTS` regex does not match `youtube-nocookie.com` — privacy-conscious embed URLs are silently downgraded to plain anchors

**File:** `frontend/src/lib/popup-rich-text.ts:29`

**Issue:** `YT_HOSTS = /^https?:\/\/(www\.)?(youtube\.com|youtu\.be)/i` does not include
`youtube-nocookie.com`. The privacy-enhanced embed domain is in wide use:
`https://www.youtube-nocookie.com/embed/<ID>` is produced by YouTube's "privacy-enhanced
mode" share dialog.

When a user pastes a `youtube-nocookie.com` URL into a feature attribute and it flows
through `classifyUrl()`, the `normalizeYouTubeEmbed` check fails (returns null), and the
URL falls through to `kind: 'other'` — rendered as a plain anchor, not an inline player.

This is a feature gap, not a security risk. It's worth noting so future maintainers
understand why `youtube-nocookie.com` URLs do not embed.

**Fix:** Extend the `YT_HOSTS` and `YT_ID_RE` patterns, or add a separate branch:

```typescript
const YT_HOSTS = /^https?:\/\/(www\.)?(youtube\.com|youtube-nocookie\.com|youtu\.be)/i;
```

The `normalizeYouTubeEmbed` return value should stay `https://www.youtube.com/embed/${id}`
(the standard, not nocookie, embed URL), or use `youtube-nocookie.com/embed/${id}` — that
choice is a product decision about default privacy level.

---

### IN-02: `useFilteredFeatureCount` — stale count not reset when the filter tab is hidden or a non-filter-supporting layer is selected

**File:** `frontend/src/components/builder/hooks/use-filtered-feature-count.ts:27-71`

**Issue:** The hook correctly returns `null` when `layer` is null or when `layer.filter`
is falsy (line 30–34 early return). However, the early return only calls `setCount(null)`;
it does not clear the `idle` listener from a prior run. Because the `useEffect` cleanup
runs before the next effect application (React guarantees this), the prior listener IS
cleaned up correctly via `return () => { cancelled = true; ... map.off('idle', handleIdle) }`.

This is not a listener leak. The cleanup is correct.

However, there is a minor stale-display issue: when the user switches from a layer with a
filter (`count = 3`) to a layer without a filter, the effect re-runs with the new layer's
`filter` being falsy, and calls `setCount(null)`. The `null` resets the display. This is
correct.

The note here is that the `setCount(null)` in the `if (!layer.filter)` branch correctly
resets the hint but also triggers a React re-render. Given that this is already inside a
`useEffect`, the re-render is fine. **No fix required** — this is documentation of
confirmed-correct behavior for future reviewers.

---

_Reviewed: 2026-05-28_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
