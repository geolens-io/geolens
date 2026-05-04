# /docs-site-audit - getgeolens.com/docs Operations Audit

Audit GeoLens docs and marketing operations for launch readiness, docs URL health, OpenAPI reference freshness, screenshot assets, Open Graph image coverage, and external links. This command is read-only unless the user explicitly asks to refresh artifacts.

**Usage:** `/docs-site-audit` (full audit) or `/docs-site-audit <scope> [target-url]` where scope is `launch`, `openapi`, `screenshots`, `og`, `links`, or `build`

Arguments: $ARGUMENTS

---

## INTAKE (Serial - do this first)

### Step 1: Resolve target URLs and site package

```bash
ARGS="$ARGUMENTS"
SCOPE="$(printf '%s\n' "$ARGS" | awk '{print $1}')"
case "$SCOPE" in
  ""|launch|openapi|screenshots|og|links|build) ;;
  http*) SCOPE="";;
  *) SCOPE="";;
esac
TARGET="$(printf '%s\n' "$ARGS" | awk '{for (i=1; i<=NF; i++) if ($i ~ /^https?:/) {print $i; exit}}')"
TARGET="${TARGET:-https://docs.getgeolens.com}"
echo "Scope: ${SCOPE:-full}"
echo "Target: $TARGET"

# Prefer an explicit docs/marketing repo path when provided by env.
if [ -n "$DOCS_SITE_DIR" ]; then
  echo "DOCS_SITE_DIR=$DOCS_SITE_DIR"
fi

# Discover likely site packages from the current repo and siblings.
find . .. -maxdepth 4 -not -path "*/node_modules/*" \( \
  -name "astro.config.mjs" -o \
  -name "astro.config.ts" -o \
  -path "*/docs/src/content/openapi/geolens.json" -o \
  -path "*/src/pages/og/\[slug\].png.ts" \
\) 2>/dev/null | sort
```

If no docs/site app is present, continue with public URL checks and report local artifact checks as skipped.

### Step 2: Read site scripts and routing metadata

```bash
SITE_DIR="${DOCS_SITE_DIR:-}"
if [ -z "$SITE_DIR" ]; then
  SITE_DIR=$(find . .. -maxdepth 4 -name "package.json" -not -path "*/node_modules/*" -print 2>/dev/null | while read pkg; do
    if grep -Eq '"astro"|"@astrojs/starlight"|"fetch-openapi"|"capture"' "$pkg"; then
      dirname "$pkg"
      break
    fi
  done)
fi

if [ -n "$SITE_DIR" ] && [ -f "$SITE_DIR/package.json" ]; then
  echo "Site dir: $SITE_DIR"
  cat "$SITE_DIR/package.json"
  find "$SITE_DIR" -maxdepth 3 \( -name "astro.config.*" -o -name "playwright.config.*" -o -name "wrangler.toml" \) -type f -print
fi
```

### Step 3: Public URL preflight

```bash
for url in \
  https://getgeolens.com \
  https://getgeolens.com/docs \
  https://docs.getgeolens.com \
  https://getgeolens.com/robots.txt \
  https://getgeolens.com/sitemap-index.xml; do
  echo "=== $url ==="
  curl -I -L --max-time 20 "$url" 2>/dev/null | sed -n '1,12p'
done

# Treat https://getgeolens.com/docs as a canonical alias/redirect check for docs.getgeolens.com.

dig +short getgeolens.com 2>/dev/null
dig +short docs.getgeolens.com 2>/dev/null

if [ -n "$SITE_DIR" ]; then
  find "$SITE_DIR/public" -maxdepth 1 \( -name "llms.txt" -o -name "robots.txt" -o -name "_redirects" \) -type f -print
fi
```

---

## AUDIT CHECKS

### 1. Launch status and production operations

Check:
- apex, `www`, `/docs`, and `docs.getgeolens.com` resolve to the intended production surface
- redirects are canonical and do not create loops or mixed docs domains
- HTTP status is 200/3xx as expected; HTTP 522 is a launch blocker
- `robots.txt` allows intended indexing and references the sitemap
- `sitemap-index.xml` is reachable and includes docs URLs
- GA4 fires on public pages when analytics is expected
- Cloudflare Pages deployment, production branch, custom domains, and env var names are correct when authenticated tooling is available

Never mutate Cloudflare, DNS, GA4, Search Console, or git state during this audit.

### 2. OpenAPI docs refresh readiness

Locate the docs OpenAPI artifact and refresh script:

```bash
if [ -n "$SITE_DIR" ]; then
  find "$SITE_DIR" \( -path "*/openapi/geolens.json" -o -name "geolens.json" \) -type f 2>/dev/null | sort
  cat "$SITE_DIR/package.json" 2>/dev/null | grep -n "fetch-openapi\|openapi"
fi

API_ORIGIN="${API_ORIGIN:-http://localhost:${API_PORT:-8001}}"
curl -sf "$API_ORIGIN/openapi.json" >/tmp/geolens-openapi-live.json 2>/dev/null && python3 -m json.tool /tmp/geolens-openapi-live.json >/dev/null
```

Verify:
- docs OpenAPI JSON comes from the current backend API, not a stale copied file
- refresh script is documented (`npm run fetch-openapi` or equivalent)
- old vs new OpenAPI comparison checks removed paths/methods, required field additions, enum narrowing, and response schema removals
- docs build succeeds after refresh

### 3. Screenshot asset freshness

Check:
- the site package has a screenshot capture command (`npm run capture` or equivalent)
- capture preflight confirms the app/docs target is running
- changed screenshots are reviewed for dimensions, blank pages, login screens, broken map tiles, and stale UI
- screenshot output paths match the docs site's expected asset locations

Use image diff or `view_image` for representative changed screenshots when refreshing artifacts.

### 4. Open Graph coverage

Check:
- `src/pages/og/[slug].png.ts` or docs equivalent exists
- every eligible docs page has one OG image reference
- every OG slug has a referring page
- every `/og/<slug>.png` route renders 200, returns an image content type, and is nonblank
- OG titles/descriptions match current page titles and do not reference retired product claims

Prefer AST parsing of the OG slug map when possible.

### 5. External and internal link health

Check:
- docs markdown/MDX links resolve, including anchors
- public external links return 200/3xx without redirect loops or expired domains
- links to install, cloud deployment, CLI, SDKs, OpenAPI, GitHub, and demo routes point at canonical destinations
- old root-repo docs stubs point to the canonical docs site and do not conflict with live pages

Run a repo-native link checker if present. Otherwise use a scoped tool such as `lychee` only if already installed.

### 6. Build and verification parity

If a local site package exists, run cheap gates before heavy visual checks:

```bash
if [ -n "$SITE_DIR" ] && [ -f "$SITE_DIR/package.json" ]; then
  cd "$SITE_DIR" && npm run
fi
```

Identify the documented commands for:
- docs build
- Astro diagnostics/type check
- link checks
- screenshot capture
- OG render validation
- visual smoke or accessibility checks

Flag any production launch checklist item that has no local/CI command as P1.

---

## DELIVERY

Write full reports to `docs-internal/audits/docs-site-audit-{YYYYMMDD}.md`.

Report structure:
- Launch blockers and warnings
- OpenAPI freshness status
- Screenshot and OG coverage status
- Link-check findings
- Local/CI command parity gaps
- Commands run and skipped checks with reasons

---

## RELATIONSHIP TO OTHER COMMANDS

- `/launch-status` checks production launch state. This command includes it as one docs-site workstream.
- `/openapi-refresh` refreshes docs OpenAPI artifacts. This command verifies whether that workflow is current and gated.
- `/screenshot-refresh` refreshes visual assets. This command audits freshness and review discipline.
- `/og-check` verifies OG image coverage. This command adds it to the broader docs operations picture.
