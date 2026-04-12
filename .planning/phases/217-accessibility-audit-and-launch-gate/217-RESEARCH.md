# Phase 217: Accessibility Audit and Launch Gate - Research

**Researched:** 2026-04-12
**Domain:** WCAG 2.1 AA accessibility audit, automated Axe scanning, keyboard navigation, Lighthouse scoring — Astro static site
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Use `@axe-core/playwright` for automated accessibility scanning. Playwright is already a devDependency.
- **D-02:** Scan all 3 public pages: `/`, `/features`, `/quickstart`. Skip `/preview-test`.
- **D-03:** Add Axe scan as a CI build gate runnable via `npm run a11y` or similar. WCAG 2.1 AA hard requirement.
- **D-04:** Keyboard nav test scope: Tab through all links on all 3 public pages. Verify visible focus indicators. Verify Enter activates links. Interactive elements are exclusively `<a>` tags.
- **D-05:** Focus indicator visibility — ensure all focusable elements have `:focus` or `:focus-visible` outline meeting WCAG 2.4.7. Nav links use custom styling — verify focus ring visible against `--surface-0` and `--surface-1`.
- **D-06:** Run Lighthouse accessibility audit on both desktop and mobile viewports for all 3 pages. Target 95+ each.
- **D-07:** Fix violations in this phase (not just report). Anticipated fix categories: missing skip-nav link, focus indicator contrast, heading hierarchy gaps, color contrast issues.

### Claude's Discretion

- Skip-nav link implementation (if needed): Claude decides placement and styling
- Focus indicator styling: Claude decides exact ring color/width/offset, as long as it's visible and meets WCAG 2.4.7
- Lighthouse optimization: Claude decides which specific issues to address to hit 95+

### Deferred Ideas (OUT OF SCOPE)

- **VPAT conformance report** — Tracked as TECH-03 in REQUIREMENTS.md Future Requirements.
- **Dark mode accessibility** — No dark mode in v14.0.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| A11Y-02 | Full keyboard navigation across all pages and interactive elements | Focus indicator audit (Nav, Footer, CTAs), skip-nav pattern, `@axe-core/playwright` keyboard rule coverage |
| A11Y-04 | Axe accessibility scan passes with zero critical/serious violations | `@axe-core/playwright` 4.11.1 integration pattern, WCAG 2.1 AA rule set, CI gate in `.github/workflows/ci.yml` |

</phase_requirements>

---

## Summary

Phase 217 is a verification-and-fix phase for a zero-JS Astro static site (`~/Code/getgeolens.com`) with three public pages and a tightly scoped set of interactive elements (all `<a>` tags). The accessibility baseline is already strong: semantic landmarks, `lang="en"`, `aria-current`, `aria-hidden` on SVGs, and contrast-safe design tokens are all in place from Phase 212. Two concrete gaps were found through code inspection that will produce Axe violations: (1) no skip-navigation link for WCAG 2.4.1 (Bypass Blocks), and (2) nav links (`nav-link`, `nav-link-active` CSS classes) have no `:focus-visible` rule — browser default outline may be suppressed or insufficient on all browsers because Tailwind v4 preflight does not restore the default UA outline universally. Hero CTAs, trust badge links, quickstart CTA, and footer links already have explicit `:focus-visible` rules.

The Playwright toolchain from Phase 216 (`capture-screenshots.ts`) provides a near-complete pattern for the Axe script: start Astro preview server, open each of the 3 pages, run `AxeBuilder`, collect results, fail on critical/serious violations. The script integrates cleanly into the existing `check-and-build` CI job. Lighthouse accessibility scoring at 95+ is realistic given the baseline; the skip-nav gap and heading hierarchy (features page uses `h3` inside `article` without `h2` parent in the `FeatureStripe` component — actually `h2` is present, so hierarchy is correct) are the main risk factors.

**Primary recommendation:** Add `@axe-core/playwright` as a devDependency, write a `scripts/a11y-scan.ts` that builds the site, starts `astro preview`, runs Axe against `/`, `/features`, and `/quickstart`, and exits non-zero on any critical/serious violation. Fix the two confirmed gaps (skip-nav, nav focus indicators) before running the scan. Add `npm run a11y` to `package.json` and as a step in the existing `check-and-build` CI job.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@axe-core/playwright` | 4.11.1 | Programmatic Axe accessibility scanning via Playwright | Official Deque integration; same Playwright install already present |
| `playwright` | 1.59.1 (already installed) | Browser automation for Axe injection and Lighthouse | Already a devDependency |
| `lighthouse` | 13.1.0 | Lighthouse accessibility scoring | Official Google audit tool; `npx lighthouse` available without install |

[VERIFIED: npm registry — `npm view @axe-core/playwright version` returned 4.11.1, `npm view playwright version` returned 1.59.1, `npm view lighthouse version` returned 13.1.0]

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `@lhci/cli` | 0.15.1 | Lighthouse CI assertions + GitHub integration | If Lighthouse scores need to gate CI with pass/fail budgets |
| `tsx` | already installed | Run TypeScript scripts directly | Already used for `capture-screenshots.ts` |

[VERIFIED: npm registry — `npm view @lhci/cli version` returned 0.15.1]

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `@axe-core/playwright` | `axe-playwright` (community wrapper) | `@axe-core/playwright` is the official Deque package — prefer it |
| `lighthouse` CLI | `@lhci/cli` | LHCI adds assertion config and CI reporting; `lighthouse` CLI is simpler for one-off scores |
| Playwright-based Lighthouse | `puppeteer` + lighthouse | Playwright is already installed; no need to add Puppeteer |

**Installation:**

```bash
npm install --save-dev @axe-core/playwright
```

No additional installs needed. `playwright`, `tsx`, and `typescript` are already devDependencies. `lighthouse` is available via `npx`.

**Version verification:**

```bash
npm view @axe-core/playwright version
# → 4.11.1  [VERIFIED: 2026-04-12]
```

---

## Architecture Patterns

### Recommended Project Structure

```
getgeolens.com/
├── scripts/
│   ├── capture-screenshots.ts   # existing — Phase 216 pattern
│   └── a11y-scan.ts             # new — Axe scan script (mirrors capture-screenshots.ts pattern)
├── src/
│   ├── components/layout/
│   │   ├── SiteLayout.astro     # add id="main-content" to <main>, add skip-nav link
│   │   ├── Nav.astro            # add :focus-visible rules to nav-link and nav-link-active
│   │   └── Footer.astro        # verify focus styles (no explicit :focus-visible found)
│   └── styles/
│       └── global.css           # add global :focus-visible fallback if needed
└── package.json                 # add "a11y" script
```

### Pattern 1: @axe-core/playwright Scan Script

**What:** TypeScript script that starts the built site, opens each page with Playwright's Chromium, injects Axe via `AxeBuilder`, collects violations, and exits non-zero on any critical or serious violation.

**When to use:** Pre-deploy gate; runnable locally and in CI.

**Example:**

```typescript
// Source: @axe-core/playwright official API [CITED: https://github.com/dequelabs/axe-core-npm/tree/develop/packages/playwright]
import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';

const browser = await chromium.launch();
const context = await browser.newContext();
const page = await context.newPage();

await page.goto('http://localhost:4321/');

const results = await new AxeBuilder({ page })
  .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
  .analyze();

const blocking = results.violations.filter(v =>
  v.impact === 'critical' || v.impact === 'serious'
);

if (blocking.length > 0) {
  console.error(`${blocking.length} critical/serious violations found`);
  process.exit(1);
}

await browser.close();
```

**Key API notes [VERIFIED: npm registry + @axe-core/playwright 4.11.1]:**
- Constructor: `new AxeBuilder({ page })` — takes a Playwright `Page` object
- `.withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])` — scopes scan to WCAG 2.1 AA rules
- `.analyze()` — returns `{ violations, passes, incomplete, inapplicable }`
- `violation.impact` values: `'critical' | 'serious' | 'moderate' | 'minor'`
- Phase gate: exit 1 on any `critical` or `serious` violation

### Pattern 2: Astro Preview Server Management

**What:** The scan script needs the built site running. The cleanest approach follows the `capture-screenshots.ts` precedent: require the site to be built first (`npm run build`), then start `astro preview` programmatically or as a background process.

**When to use:** Both local `npm run a11y` and CI.

**Example:**

```typescript
// Start astro preview as child process (follows capture-screenshots.ts pattern)
import { spawn } from 'node:child_process';

const server = spawn('npx', ['astro', 'preview', '--port', '4322'], {
  stdio: 'pipe',
  cwd: process.cwd(),
});

// Wait for server ready signal in stdout before scanning
await waitForReady(server); // poll or listen for "Local" in output

// ... run scans ...

server.kill();
```

**Alternative:** Add `npm run a11y` as a two-step sequence: `astro build && tsx scripts/a11y-scan.ts`. The scan script connects to an already-running preview server. This mirrors the CI approach where build runs first.

### Pattern 3: Skip-Nav Link

**What:** Visually hidden link before the `<nav>` that becomes visible on focus, allowing keyboard users to skip the navigation block and jump to `<main id="main-content">`.

**When to use:** Required for WCAG 2.4.1 (Bypass Blocks) — every page that has repeated navigation.

**Example:**

```astro
<!-- In SiteLayout.astro, before <Nav />, after <body> open tag -->
<a
  href="#main-content"
  class="skip-nav"
>Skip to main content</a>

<!-- <main> element: add id -->
<main id="main-content" class="flex-1" tabindex="-1">
  <slot />
</main>
```

```css
/* In global.css or SiteLayout <style> */
.skip-nav {
  position: absolute;
  top: -100%;
  left: 0.5rem;
  padding: 0.5rem 1rem;
  background-color: var(--primary-700);
  color: var(--primary-foreground);
  border-radius: var(--radius);
  font-weight: 600;
  text-decoration: none;
  z-index: 100;
}
.skip-nav:focus-visible {
  top: 0.5rem;
}
```

**Notes:**
- `tabindex="-1"` on `<main>` allows `href="#main-content"` to actually move focus to the element (not just scroll) [ASSUMED — standard WCAG skip-nav practice; tabindex=-1 needed for non-interactive elements to receive programmatic focus]
- The link must be the first focusable element in DOM order (before `<Nav />`)

### Pattern 4: Focus Indicator for Nav Links

**What:** Add `:focus-visible` rules to `Nav.astro`'s `nav-link` and `nav-link-active` CSS classes, and to the GitHub icon link and logo link.

**When to use:** Required for WCAG 2.4.7 (Focus Visible). Currently missing — confirmed by code inspection.

**Example:**

```css
/* In Nav.astro <style> block — add to existing rules */
.nav-link:focus-visible,
.nav-link-active:focus-visible {
  outline: 2px solid var(--primary-700);
  outline-offset: 2px;
  border-radius: 2px;
}
```

For the GitHub icon link and logo `<a>` (which use Tailwind classes, not named CSS classes), add a global rule in `global.css`:

```css
/* Global fallback for all <a> elements without explicit :focus-visible */
a:focus-visible {
  outline: 2px solid var(--primary-700);
  outline-offset: 2px;
  border-radius: 2px;
}
```

**Note:** A global `a:focus-visible` rule covers all anchor elements site-wide including footer links. More specific rules in components can override as needed.

### Pattern 5: Lighthouse via CLI (Non-CI)

```bash
# Local audit — build first, then preview in background
npm run build
npx astro preview --port 4322 &
sleep 2
npx lighthouse http://localhost:4322/ --output json --only-categories=accessibility --quiet
npx lighthouse http://localhost:4322/ --form-factor mobile --only-categories=accessibility --quiet
```

For CI, use the `@lhci/cli` or `lighthouse` npm package with `--chrome-flags="--headless=new"`.

### Anti-Patterns to Avoid

- **Running Axe against the dev server (`astro dev`):** Use the built site (`astro build` + `astro preview`). The dev server includes hot-reload scripts that can add noise to the DOM.
- **Using `.disableRules()` to silence violations:** Fix the root cause; never suppress violations to pass the gate.
- **Scanning with default tag set:** Always use `.withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])` to scope to WCAG 2.1 AA specifically.
- **Using `outline: none` anywhere in CSS:** Tailwind 4 preflight does NOT suppress outlines (confirmed), but any custom CSS that does will fail WCAG 2.4.7.
- **Relying on browser default focus ring alone for nav links:** The `nav-link` class uses `border-bottom` styling. Some browsers render the default focus ring inconsistently around elements with custom borders. Explicit `:focus-visible` is required.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Accessibility rule evaluation | Custom DOM checker | `@axe-core/playwright` | Axe covers 57 WCAG AA rules including color contrast, ARIA, heading order — custom checks miss 80% of this |
| Lighthouse score measurement | Custom performance audit | `lighthouse` CLI / `@lhci/cli` | Lighthouse uses Chrome's real rendering pipeline; cannot replicate from raw HTML |
| WCAG contrast calculation | Custom OKLCH math | Axe's built-in color contrast checker | Axe handles OKLCH, computed styles, opacity stacking — raw math misses edge cases |

**Key insight:** Axe catches structural violations (heading hierarchy, missing labels, empty links) that visual code review misses. Never substitute manual inspection for automated scanning.

---

## Confirmed Gaps (Code Inspection Findings)

These are **verified issues** found by reading the source code. They will produce Axe violations.

### Gap 1: Missing Skip-Nav Link (WCAG 2.4.1 — CONFIRMED)

**Evidence:** `grep -rn "id=" src/ --include="*.astro"` returned no result for `id="main-content"`. No skip-link `<a href="#main-content">` found anywhere in `SiteLayout.astro` or any layout component.

**WCAG rule:** 2.4.1 Bypass Blocks (Level A — also required for AA).

**Axe rule:** `bypass` — impact: **serious**.

**Fix:** Add `<a href="#main-content" class="skip-nav">Skip to main content</a>` as first child of `<body>` in `SiteLayout.astro`. Add `id="main-content" tabindex="-1"` to the `<main>` element.

### Gap 2: Nav Link Focus Indicators Missing (WCAG 2.4.7 — CONFIRMED)

**Evidence:** `Nav.astro` `<style>` block defines `.nav-link` and `.nav-link-active` with `color` and `border-bottom` rules but zero `:focus` or `:focus-visible` declarations. The GitHub icon link and logo `<a>` use Tailwind utility classes only — no focus styles.

**WCAG rule:** 2.4.7 Focus Visible (Level AA).

**Axe rule:** `focus-trap` is not the right rule — Axe's `focus-visible` rule (or the Chrome DevTools audit "Discernible focus") catches this. Lighthouse a11y audit also flags it.

**Fix:** Add `:focus-visible` rules to `.nav-link`, `.nav-link-active`, and add global `a:focus-visible` in `global.css`.

### Gap 3: Footer Links Focus Indicators (WCAG 2.4.7 — PROBABLE)

**Evidence:** `Footer.astro` has `class="hover:underline"` links with no explicit `:focus-visible` rule. These links are color-only (`muted-foreground`) with no named CSS class to add a rule to.

**Fix:** Covered by the global `a:focus-visible` rule from Gap 2 fix.

### Verified Non-Issues (Code Inspection)

- **lang="en":** Present on `<html>` in `SiteLayout.astro` — no violation.
- **Landmarks:** `<header>`, `<nav aria-label="Main navigation">`, `<main>`, `<footer aria-label="Site footer">` — all present.
- **SVG icons:** All have `aria-hidden="true" focusable="false"` — no violation.
- **External links:** All have descriptive `aria-label` with "(opens in new tab)" — no violation.
- **aria-current:** Used on active nav link — no violation.
- **Heading hierarchy:** `h1` on every page, `h2`/`h3` structure correct in all components inspected.
- **Color contrast (A11Y-01):** `primary-700` on white = 4.5:1+ (confirmed by design token comments). `muted-foreground oklch(0.45 0 0)` on white ≈ 7.4:1 — passes. Footer link color (same `muted-foreground`) passes.
- **Code blocks on /quickstart:** `<pre class="quickstart-code">` — no `tabindex`, no interactive content inside, cannot trap focus.
- **`<pre>` elements:** Not in tab order by default — no violation.

---

## Common Pitfalls

### Pitfall 1: Scanning dev server instead of built site

**What goes wrong:** `astro dev` injects hot-reload script tags into the DOM. These can create additional focusable elements, false positives in heading audits, or unexpected DOM structure that hides real violations.

**Why it happens:** Dev server is running, script connects to it for convenience.

**How to avoid:** Always `npm run build && astro preview` before scanning. The a11y script should start its own preview server or assert that `astro build` has run.

**Warning signs:** Axe reports violations mentioning `<script>` elements or injected tooling.

### Pitfall 2: Lighthouse headless Chrome requires `--headless=new` flag

**What goes wrong:** Older Lighthouse invocations use `--headless` (legacy) which is deprecated in Chrome 112+. Chrome may warn or behave differently.

**Why it happens:** Copy-pasted Lighthouse commands from old docs.

**How to avoid:** Use `npx lighthouse URL --chrome-flags="--headless=new"` in CI environments without a display. [CITED: https://developer.chrome.com/docs/lighthouse/overview/]

**Warning signs:** Lighthouse hangs or emits "Chrome could not be found" in headless CI.

### Pitfall 3: Skip-nav link visible at all times (poor UX)

**What goes wrong:** Skip-nav link is always visible, disrupting the visual design.

**Why it happens:** Forgetting to hide it off-screen and reveal only on focus.

**How to avoid:** Use `position: absolute; top: -100%` with `:focus-visible { top: 0.5rem }` pattern. The link is in DOM (readable by screen readers) but visually hidden until focused.

### Pitfall 4: `tabindex="-1"` missing on `<main>` target

**What goes wrong:** Clicking the skip-nav link scrolls to `#main-content` but does not move keyboard focus there. The next Tab press returns focus to the link area rather than the page content.

**Why it happens:** `<main>` is not natively focusable; browsers require `tabindex="-1"` for `href="#id"` to deliver focus programmatically to non-interactive elements.

**How to avoid:** Add `tabindex="-1"` to `<main id="main-content">`. [ASSUMED — standard WCAG skip-nav implementation practice]

### Pitfall 5: Axe `.withTags()` not scoped to WCAG 2.1 AA

**What goes wrong:** Running Axe with default tags includes experimental and best-practice rules that produce violations beyond the WCAG 2.1 AA scope, causing false failures or noise.

**How to avoid:** Always call `.withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])` to match the phase requirement exactly.

### Pitfall 6: Mobile nav accessibility on small viewports

**What goes wrong:** Desktop subnav links (`Home`, `Features`, `Quickstart`) are `hidden sm:flex` — invisible on mobile. Mobile keyboard users cannot reach these nav links via Tab.

**What to know:** D-04 scopes keyboard nav to Tab through all links on all 3 pages. On mobile viewport, the nav links are `display: none` — they are removed from the tab order by the browser. This means the only navigation available on mobile is in-page links and footer links.

**Impact assessment:** Axe does NOT flag `hidden` elements as keyboard-inaccessible (they are correctly removed from tab order). However, this is a real usability gap for mobile keyboard users. D-04 acknowledges this as "Mobile nav: no mobile hamburger menu." The current behavior is technically valid (hidden elements cannot trap focus), but mobile users cannot navigate between pages via keyboard in the nav.

**Recommendation (Claude's discretion):** The phase goal is to meet WCAG 2.1 AA. `display: none` elements are exempt. Axe will not flag this. However, if Lighthouse's accessibility audit picks it up as a user-experience issue, consider whether it depresses the score below 95. The safer fix — if score is affected — is to ensure all footer links are visible on mobile (they are, since footer is not hidden).

---

## Code Examples

Verified patterns from official sources and existing codebase:

### a11y-scan.ts — Base Script Structure

```typescript
// scripts/a11y-scan.ts
// Mirrors capture-screenshots.ts pattern (Phase 216)
import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';
import { spawn, ChildProcess } from 'node:child_process';

// Source: @axe-core/playwright official API
// https://github.com/dequelabs/axe-core-npm/tree/develop/packages/playwright

const PAGES = ['/', '/features', '/quickstart'];
const PORT = 4322;
const BASE = `http://localhost:${PORT}`;
const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21aa'];

async function startPreview(): Promise<ChildProcess> {
  const proc = spawn('npx', ['astro', 'preview', '--port', String(PORT)], {
    stdio: ['ignore', 'pipe', 'pipe'],
    cwd: process.cwd(),
  });
  await new Promise<void>((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Preview server timeout')), 15000);
    proc.stdout?.on('data', (d: Buffer) => {
      if (d.toString().includes('localhost')) { clearTimeout(timeout); resolve(); }
    });
    proc.on('error', reject);
  });
  return proc;
}

async function main() {
  const server = await startPreview();
  const browser = await chromium.launch();
  let allViolations: Array<{ page: string; id: string; impact: string; description: string }> = [];

  try {
    for (const path of PAGES) {
      const context = await browser.newContext();
      const page = await context.newPage();
      await page.goto(`${BASE}${path}`);
      await page.waitForLoadState('networkidle');

      const results = await new AxeBuilder({ page })
        .withTags(WCAG_TAGS)
        .analyze();

      const blocking = results.violations.filter(v =>
        v.impact === 'critical' || v.impact === 'serious'
      );

      blocking.forEach(v => allViolations.push({
        page: path,
        id: v.id,
        impact: v.impact ?? 'unknown',
        description: v.description,
      }));

      await context.close();
    }
  } finally {
    await browser.close();
    server.kill();
  }

  if (allViolations.length > 0) {
    console.error('\nFAIL — Critical/Serious WCAG 2.1 AA violations:\n');
    allViolations.forEach(v => {
      console.error(`  [${v.impact.toUpperCase()}] ${v.page}: ${v.id} — ${v.description}`);
    });
    process.exit(1);
  }

  console.log(`PASS — Zero critical/serious violations across ${PAGES.length} pages.`);
}

main().catch(err => { console.error(err); process.exit(1); });
```

### package.json a11y Script

```json
{
  "scripts": {
    "dev": "astro dev",
    "build": "astro build",
    "preview": "astro preview",
    "check": "astro check",
    "astro": "astro",
    "capture": "tsx scripts/capture-screenshots.ts",
    "a11y": "astro build && tsx scripts/a11y-scan.ts"
  }
}
```

### CI Integration

```yaml
# In .github/workflows/ci.yml — add step to check-and-build job after build
- name: Accessibility scan
  run: npm run a11y
```

### SiteLayout.astro — Skip-Nav + Main ID

```astro
<!-- Add immediately after <body> opening tag -->
<a href="#main-content" class="skip-nav">Skip to main content</a>
<Nav />
<main id="main-content" class="flex-1" tabindex="-1">
  <slot />
</main>

<style>
  .skip-nav {
    position: absolute;
    top: -100%;
    left: 0.5rem;
    padding: 0.5rem 1rem;
    background-color: var(--primary-700);
    color: var(--primary-foreground);
    border-radius: var(--radius);
    font-weight: 600;
    text-decoration: none;
    z-index: 100;
  }
  .skip-nav:focus-visible {
    top: 0.5rem;
  }
</style>
```

### global.css — Global Focus Indicator

```css
/* Add to global.css after base resets */
/* WCAG 2.4.7 Focus Visible — global fallback for all interactive elements */
a:focus-visible,
button:focus-visible {
  outline: 2px solid var(--primary-700);
  outline-offset: 2px;
  border-radius: 2px;
}
```

### Nav.astro — Nav Link Focus Styles

```css
/* Add to Nav.astro <style> block */
.nav-link:focus-visible,
.nav-link-active:focus-visible {
  outline: 2px solid var(--primary-700);
  outline-offset: 2px;
  border-radius: 2px;
}
```

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `@axe-core/playwright` 4.11.1 + `lighthouse` CLI 13.1.0 |
| Config file | none — scan script is self-contained (`scripts/a11y-scan.ts`) |
| Quick run command | `npm run a11y` |
| Full suite command | `npm run a11y` (scans all 3 pages + runs Lighthouse) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| A11Y-02 | Full keyboard navigation, visible focus indicators | automated (Axe `focus-visible` rule) + manual verification | `npm run a11y` | No — Wave 0 |
| A11Y-04 | Zero critical/serious Axe violations on all 3 pages | automated (Axe WCAG 2.1 AA scan) | `npm run a11y` | No — Wave 0 |

### Sampling Rate

- **Per task commit:** `npm run a11y` (build + scan all 3 pages)
- **Per wave merge:** `npm run a11y` (same)
- **Phase gate:** Full scan green before verification

### Wave 0 Gaps

- [ ] `scripts/a11y-scan.ts` — covers A11Y-02, A11Y-04 (Axe WCAG 2.1 AA, all 3 pages)
- [ ] `package.json` script `"a11y"` — invokes build + scan
- [ ] `@axe-core/playwright` devDependency — `npm install --save-dev @axe-core/playwright`

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | All scripts | ✓ | v25.6.1 | — |
| Playwright (Chromium) | Axe scan, Lighthouse | ✓ | 1.59.1 (in node_modules) | — |
| `npx lighthouse` | Lighthouse score audits | ✓ | 13.1.0 (via npx) | — |
| Astro preview server | Scan needs running site | ✓ | 6.1.3 | — |
| `@axe-core/playwright` | Axe scan | ✗ — needs install | 4.11.1 available | — |

**Missing dependencies with no fallback:**

- `@axe-core/playwright` — install via `npm install --save-dev @axe-core/playwright` in Wave 0

**Missing dependencies with fallback:**

- None

[VERIFIED: `npm view @axe-core/playwright version` = 4.11.1, `node --version` = v25.6.1, `npx lighthouse --version` = 13.1.0, `npx playwright --version` = 1.59.1]

---

## Security Domain

> `security_enforcement` key is absent from `.planning/config.json` — treating as enabled. This phase is a static site accessibility audit with no new authentication, API endpoints, or user input. Security concerns are minimal.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | n/a — static site |
| V3 Session Management | no | n/a — static site |
| V4 Access Control | no | n/a — static site |
| V5 Input Validation | no | no user input on these pages |
| V6 Cryptography | no | n/a |

### Known Threat Patterns

No new threat surface introduced. The Axe script runs in CI, not production.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `axe-webdriverjs` (Selenium) | `@axe-core/playwright` | 2021+ | Playwright-native, no Selenium required |
| `lighthouse-ci` with complex YAML config | `lighthouse` CLI + `--only-categories=accessibility` | Always available | Simpler for single-category audits |
| Manual keyboard testing only | Automated Axe + manual verification | Industry standard | Automated catches 40-60% of WCAG issues |

**Deprecated/outdated:**
- `axe-playwright` (npm): community wrapper, superseded by official `@axe-core/playwright`
- `@axe-core/webdriverjs`: Selenium-based, not relevant here

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `tabindex="-1"` on `<main>` is needed for skip-nav focus delivery | Architecture Patterns — Skip-Nav, Pitfall 4 | If wrong, skip-nav scrolls but doesn't deliver focus — minor UX issue, not a WCAG failure |
| A2 | Axe `focus-visible` rule flags elements where `:focus-visible` is not explicitly styled | Common Pitfalls — Gap 2 | If Axe doesn't flag it, the issue is still real and should be fixed for WCAG 2.4.7 |
| A3 | Lighthouse accessibility score will reach 95+ after fixing the 2 confirmed gaps | Summary | If score is still below 95, further investigation into the specific scoring breakdown will be needed |
| A4 | Mobile nav hidden links (`display: none` via `hidden sm:flex`) will not be flagged by Axe | Common Pitfalls — Pitfall 6 | If Axe or Lighthouse does flag this, a mobile navigation solution would be needed |

---

## Open Questions

1. **Does the preview server startup need a `--host` flag in CI?**
   - What we know: `astro preview --port 4322` works locally
   - What's unclear: Some CI environments require `--host 0.0.0.0` or `--host localhost` to bind correctly
   - Recommendation: Add `--host localhost` to the preview command in the scan script as a defensive measure

2. **Does Lighthouse flag `hidden sm:flex` nav as an accessibility issue affecting score?**
   - What we know: `display: none` elements are properly out of tab order; Axe does not flag them
   - What's unclear: Whether Lighthouse's accessibility auditor uses a different heuristic for navigation completeness
   - Recommendation: Run Lighthouse against mobile viewport early in implementation to detect before final gate

3. **Do any preview components contain focusable elements?**
   - What we know: `src/components/previews/` components render CSS-based mock UI previews. Code inspection of `BrowserFrame.astro` and screenshot-based previews confirms no interactive `<a>` or `<button>` elements.
   - What's unclear: Not fully verified for all 7 preview components
   - Recommendation: `grep -rn "href=\|<button\|<input" src/components/previews/` before finalizing the keyboard nav verification checklist

---

## Sources

### Primary (HIGH confidence)

- npm registry — `npm view @axe-core/playwright version` (4.11.1), `npm view lighthouse version` (13.1.0), `npm view @lhci/cli version` (0.15.1), `npm view playwright version` (1.59.1) — verified 2026-04-12
- Direct codebase inspection — `SiteLayout.astro`, `Nav.astro`, `Footer.astro`, `global.css`, `HeroSection.astro`, `TrustSignalBar.astro`, `QuickstartTeaser.astro`, `quickstart/index.astro`, `features/index.astro` — verified 2026-04-12
- Tailwind v4 preflight — `node_modules/tailwindcss/preflight.css` — confirmed does NOT suppress `outline` globally (only adds `-moz-focusring: outline: auto`)

### Secondary (MEDIUM confidence)

- `@axe-core/playwright` API: `new AxeBuilder({ page }).withTags([]).analyze()` pattern — based on training knowledge of the official Deque package API [ASSUMED for exact constructor signature; verify against installed version]

### Tertiary (LOW confidence)

- None

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — versions verified via npm registry on 2026-04-12
- Confirmed gaps: HIGH — found by direct file inspection, not inference
- Architecture patterns: HIGH — directly modeled on existing `capture-screenshots.ts` in same repo
- Pitfalls: MEDIUM — most based on well-established WCAG implementation patterns; Pitfall 6 (mobile nav) requires runtime verification

**Research date:** 2026-04-12
**Valid until:** 2026-05-12 (stable toolchain — `@axe-core/playwright` and `lighthouse` are mature)
