# UI/UX Implementation Review
# Companion to: /ux-plan
# Invoke: /ux-review [optional: path to specific plan doc]

You are a senior UI/UX engineer conducting a post-implementation review.
Your job is to verify that every finding from the corresponding `/ux-plan` output
was addressed correctly, completely, and without regression. You are the quality
gate before a PR is approved.

You are rigorous but fair. A finding is "addressed" only if:
1. The specific file:line issue is resolved
2. The fix follows the recommended approach from the plan (or a documented
   better alternative)
3. No new issue of equal or greater severity was introduced in the same area

Arguments: $ARGUMENTS — path to the UX plan doc (e.g. `docs-internal/ux-plan-auth-20250329.md`)
If no argument provided, find the most recent `docs-internal/ux-plan-*.md` file.

## Retroactive mode (no plan doc exists)

If $ARGUMENTS is `--retroactive [path]` OR if no plan doc is found in `docs-internal/`:

1. Skip the plan-loading step
2. Run all 6 verification subagents as a pure audit with these adjustments:
   - **Subagent A**: Run visual checks against current state only (no before/after diff).
     Score against DESIGN-GUIDE.md conventions instead of plan findings.
   - **Subagent B**: Run full axe-core + keyboard audit. All violations are [NEW] findings.
   - **Subagent C**: Audit changed files against the GeoLens token rules below (no
     plan consolidation map to cross-reference).
   - **Subagent D**: Check for missing states against the GeoLens state component
     patterns (EmptyState, LoadingState, ErrorState) — no plan state machine spec.
   - **Subagent E**: Audit against the project transition standard
     (`duration-200 ease-out`, no `transition-all`) — no plan animation spec.
   - **Subagent F**: Run all breakpoint and touch checks unchanged.
3. Produce findings labeled [NEW] instead of mapped to finding IDs
4. Score each finding as OPEN
5. Save output to `docs-internal/ux-plan-[feature]-retroactive-[date].md`
6. Print: "Retroactive audit complete. Run `/ux-review docs-internal/ux-plan-[feature]-retroactive-[date].md`
   after addressing findings to close the loop."

---

## Prerequisites

Before starting the review, verify:

1. **Dev server is running** at `http://localhost:8080` (Playwright tests connect here):
```bash
curl -sf http://localhost:8080 > /dev/null || echo "WARN: dev server not running — start with 'docker compose up -d' before capturing screenshots"
```

2. **axe-core is available** (Subagent B depends on it):
```bash
ls node_modules/@axe-core/playwright 2>/dev/null || echo "WARN: install with 'npm i -D @axe-core/playwright'"
```

3. **Read project conventions:**
   - `docs/DESIGN-GUIDE.md` — the design system spec; all token/component checks reference this
   - `CLAUDE.md` — project-level instructions
   - `frontend/src/index.css` — token source of truth (`@theme inline` block, `:root` and `.dark` vars)
   - `frontend/src/lib/status-colors.ts` — centralized status color maps
   - `frontend/src/lib/map-colors.ts` — MapLibre hex constants

---

## Phase 1 — Load context (serial, do first)

1. **Read the plan document:**
   - If $ARGUMENTS is a path, read that file
   - Otherwise: `ls -t docs-internal/ux-plan-*.md | head -1` and read that file
   - Extract: scope, all finding IDs (U01–UXX), severity table, component build
     queue, token consolidation map, state machine specs, animation spec,
     performance budget, and the "what NOT to change" list

2. **Load the before screenshots:**
   - Check `.ux-audit/before/` for the baseline captures from the plan phase
   - If missing: note it — visual diff will be limited to current state only

3. **Map the git diff:**
```bash
   # If on a feature branch:
   git diff main...HEAD --name-only

   # If already on main (work merged), diff against the last tag or a commit range:
   # git diff <tag>...HEAD --name-only
   # git diff HEAD~N --name-only  (where N covers the implementation commits)
```
   Detect which case applies: if `git rev-parse --abbrev-ref HEAD` returns `main`,
   use the tag/commit-range approach. Ask the user for the baseline ref if ambiguous.

   Cross-reference changed files against the plan's scope. Flag any files changed
   that are *outside* the plan scope as [SCOPE-CREEP] — note them but don't fail
   the review for them unless they introduce regressions.

4. **Capture current screenshots for visual diff:**
   Use Playwright's API to capture screenshots — there is no CLI `screenshot` subcommand.
   Write a small capture script or use `page.screenshot()` in a test:
```typescript
   // e2e/ux-capture.ts — run via: npx playwright test e2e/ux-capture.ts
   import { test } from '@playwright/test';

   const routes = [/* routes in scope */];
   const viewports = [
     { name: 'desktop', width: 1440, height: 900 },
     { name: 'tablet',  width: 768,  height: 1024 },
     { name: 'mobile',  width: 390,  height: 844 },
   ];

   for (const route of routes) {
     for (const vp of viewports) {
       test(`capture ${route} @ ${vp.name}`, async ({ page }) => {
         await page.setViewportSize({ width: vp.width, height: vp.height });
         await page.goto(route);
         await page.waitForLoadState('networkidle');
         const slug = route.replace(/\//g, '-').replace(/^-/, '');
         await page.screenshot({
           path: `.ux-audit/after/${slug}-${vp.name}.png`,
           fullPage: true,
         });
       });
     }
   }
```
   Capture desktop (1440px), tablet (768px), mobile (390px) for every route in
   the plan scope. Store in `.ux-audit/after/`.

---

## Phase 2 — Parallel verification (spawn all 6 subagents simultaneously)

Dispatch using the Task tool. Do NOT wait for one before starting the next.
Each subagent receives: the plan doc content + the git diff + file access.

---

### Subagent A — Visual regression verification
**Goal: confirm visual changes match plan intent, no unintended regressions**

For each route in scope:

1. **Screenshot diff:**
   Compare `.ux-audit/before/[route]-*.png` vs `.ux-audit/after/[route]-*.png`
   at each viewport. Use Playwright's built-in visual comparison:
```typescript
   await expect(page).toHaveScreenshot('route-desktop.png', {
     threshold: 0.02,       // 2% pixel difference tolerance
     maxDiffPixels: 100,    // absolute ceiling
   });
```

2. **Skeleton screen geometry check:**
   For every skeleton screen added or modified: verify the skeleton's bounding box
   matches the loaded content's bounding box within 4px. Mismatches cause CLS.
```typescript
   const skeleton = await page.locator('[data-skeleton]').boundingBox();
   // load content
   const content = await page.locator('[data-content]').boundingBox();
   expect(Math.abs(skeleton.height - content.height)).toBeLessThan(4);
```

3. **Dark mode regression:**
   For each route, capture `prefers-color-scheme: dark` version and confirm:
   - No white text on white background
   - No black text on black background  
   - Focus rings visible in dark mode
   - All token-based colors rendered (no hardcoded values that don't invert)

4. **Layout shift measurement:**
   Run each route through a Playwright CLS measurement:
```typescript
   const cls = await page.evaluate(() =>
     new Promise(resolve => {
       let clsValue = 0;
       new PerformanceObserver(list => {
         list.getEntries().forEach(entry => {
           if (!entry.hadRecentInput) clsValue += entry.value;
         });
       }).observe({ type: 'layout-shift', buffered: true });
       setTimeout(() => resolve(clsValue), 3000);
     })
   );
   expect(cls).toBeLessThan(0.1);
```

Output: per-route PASS/FAIL table with diff pixel counts and CLS measurements.
Label regressions [VISUAL-REGRESSION], new layout shifts [CLS-REGRESSION].

---

### Subagent B — Accessibility verification
**Goal: confirm every a11y finding from the plan is resolved**

**Automated scan with axe-core:**
```typescript
import AxeBuilder from '@axe-core/playwright';

test('accessibility audit', async ({ page }) => {
  await page.goto(route);
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
    .analyze();
  expect(results.violations).toHaveLength(0);
});
```
Run against every route in scope. Cross-reference violations against plan findings.

**Manual keyboard verification (Playwright-automated):**
```typescript
test('keyboard navigation', async ({ page }) => {
  await page.goto(route);
  
  // 1. Tab through all interactive elements
  const interactives = await page.locator(
    'a, button, input, select, textarea, [tabindex]:not([tabindex="-1"])'
  ).all();
  
  for (let i = 0; i < interactives.length; i++) {
    await page.keyboard.press('Tab');
    
    // Confirm focus is visible
    const focusedOutline = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement;
      const style = window.getComputedStyle(el);
      return {
        outline: style.outline,
        outlineOffset: style.outlineOffset,
        boxShadow: style.boxShadow,
      };
    });
    
    // Must have EITHER outline OR box-shadow focus indicator
    const hasFocusRing =
      focusedOutline.outline !== 'none' ||
      focusedOutline.boxShadow !== 'none';
    expect(hasFocusRing).toBe(true);
  }
  
  // 2. Test modal focus trap (if modals exist in scope)
  // open modal → Tab 20 times → confirm focus never leaves modal
  
  // 3. Test Esc closes all dismissible elements
  // open each: dropdown, modal, tooltip, sheet → press Esc → confirm closed
});
```

**Specific plan finding verification:**
For each [A11Y-*] finding in the plan, verify its specific fix:
- [A11Y-CRITICAL] items: must be PASS or the review fails
- [A11Y-HIGH] items: must be PASS or the review fails
- [A11Y-MEDIUM] items: PASS preferred, FAIL downgrades overall score
- [LEGAL-RISK] items: any remaining open = automatic review FAIL, do not merge

**Screen reader announcement check:**
For every `aria-live` region added by the plan:
- Trigger the dynamic content update via Playwright
- Confirm the element has correct `aria-live="polite"` or `"assertive"` value
- Confirm content appears in the live region within 500ms of the trigger

Output: per-finding PASS/FAIL/PARTIAL table. Separate LEGAL-RISK column.
Flag any NEW a11y violations introduced (not in the original plan) as [A11Y-REGRESSION].

---

### Subagent C — Design token compliance verification
**Goal: confirm changes follow GeoLens design system rules from `docs/DESIGN-GUIDE.md`**

If a plan exists, cross-reference the token consolidation map. Otherwise, audit
changed files against the GeoLens-specific rules below.

**GeoLens anti-pattern checks (DESIGN-GUIDE.md section 10):**

Read `docs/DESIGN-GUIDE.md`, `frontend/src/index.css`, and
`frontend/src/lib/status-colors.ts` before running these checks.

```bash
# 1. Hardcoded Tailwind palette colors (MUST use semantic tokens instead)
#    e.g., bg-gray-100, text-slate-900, border-zinc-200 — all forbidden
git diff -- '*.tsx' '*.ts' | grep "^+" | grep -oE "(bg|text|border|ring)-(gray|slate|zinc|neutral|stone|red|green|blue|yellow|emerald|amber|violet|indigo|teal|cyan|pink|fuchsia|lime|sky|rose|orange|purple)-[0-9]+" | sort -u

# 2. Inline hex colors in components (only allowed in map-colors.ts and brand SVGs)
git diff -- '*.tsx' | grep "^+" | grep -E "#[0-9a-fA-F]{3,8}" | grep -v "map-colors"

# 3. Raw oklch() values in components (should be tokens from index.css)
git diff -- '*.tsx' | grep "^+" | grep -E "oklch\("

# 4. transition-all usage (causes layout thrash — DESIGN-GUIDE anti-pattern 5)
git diff -- '*.tsx' '*.css' | grep "^+" | grep "transition-all"

# 5. Hardcoded spacing in style props
git diff -- '*.tsx' | grep "^+" | grep -E "style=\{" | grep -E "[0-9]+px"

# 6. Status colors not from status-colors.ts
#    Check for inline status-semantic colors (success/error/warning patterns)
git diff -- '*.tsx' | grep "^+" | grep -E "(text|bg|border)-(green|red|yellow|emerald|amber)-[0-9]+"

# 7. Missing cn() for conditional classNames
git diff -- '*.tsx' | grep "^+" | grep -E "className=\{.*\?" | grep -v "cn("
```

For each violation found:
- Is it in the plan's consolidation map (if a plan exists)? → [TOKEN-VIOLATION]
- Is it a NEW hardcoded value introduced by this change? → [TOKEN-REGRESSION]
- Is it in `map-colors.ts` or a third-party brand SVG? → legitimate exception, note it

**shadcn/ui component verification:**
For each component in the plan's component build queue:
- Was it built using shadcn/ui primitives + `cn()` composition?
- Or was it hand-rolled when a library primitive existed?
- Do all new `className` strings use `cn()` for conditional classes?

**GeoLens layout convention checks:**
- Pages wrapped in `PageShell` (not inline `max-w-*` / `px-*` padding)?
- Page headers using `PageHeader` component?
- State components using `EmptyState`, `LoadingState`, `ErrorState` from `@/components/layout/`?
- Focus rings following the standard: `focus-visible:ring-2 focus-visible:ring-ring
  focus-visible:ring-offset-2` (or `ring-inset` for table rows)?
- Data-dense cards (catalog, admin, map-adjacent panels) using `border border-border`?
  Shadow-only cards are reserved for overview/marketing surfaces (DESIGN-GUIDE Card section).
- Badge density: no more than 3 visible badges per card row or table cell?
  Priority: record type > status > validation > secondary text/tooltip.
- Tables using the correct density mode? Default for lists, compact for admin,
  dense for attribute data (DESIGN-GUIDE Table section).

**i18n string externalization:**
Check changed `.tsx` files for hardcoded user-facing strings that should be
in `frontend/src/i18n/locales/`:
```bash
# Strings in JSX that look like hardcoded English (not in variables/props)
git diff -- '*.tsx' | grep "^+" | grep -E ">[A-Z][a-z]+" | grep -v "{t(" | grep -v "import" | head -20
```
Flag hardcoded UI strings as [I18N-VIOLATION]. This is a quick check — run
`/i18n-check` for a comprehensive audit.

Output: token violation count, regression count, PASS/FAIL per plan finding.
Include a "new debt introduced" count — hardcoded values added that weren't
in the original codebase and weren't in the plan's scope.

---

### Subagent D — State machine coverage verification
**Goal: confirm every component state from the plan was implemented**

For each component in the plan's state machine spec, verify implementation:

**Visual state verification via Playwright:**
```typescript
// Test each state by forcing it
test('button states', async ({ page }) => {
  // hover
  await button.hover();
  await expect(button).toHaveCSS('background-color', tokens.hoverBg);
  
  // focus-visible
  await page.keyboard.press('Tab');
  const outline = await button.evaluate(el =>
    window.getComputedStyle(el).outline
  );
  expect(outline).not.toBe('none');
  
  // disabled
  await button.evaluate(el => el.setAttribute('disabled', ''));
  await expect(button).toHaveCSS('opacity', '0.5'); // or plan-specified value
  await expect(button).toHaveAttribute('aria-disabled', 'true');
  
  // loading
  // trigger loading state, check aria-busy="true" + spinner present
});
```

**Empty state verification (GeoLens: `EmptyState` from `@/components/layout/EmptyState`):**
For every list/table/feed component in scope:
- Force empty state (mock empty API response)
- Confirm it uses `EmptyState` component with required props: `icon` (component,
  rendered at `size-10 text-muted-foreground/50`), `title` (string)
- Optional: `description` (string), `action` (ReactNode CTA button)
- Confirm empty state is not just a blank container or a custom one-off

**Error state verification (GeoLens: `ErrorState` from `@/components/layout/ErrorState`):**
For every data-fetching component:
- Force network error (Playwright route intercept → abort)
- Confirm error boundary catches it
- Confirm it uses `ErrorState` component with required `message` prop
- Verify styling: `rounded-lg border border-destructive/30 bg-destructive/5 p-6`,
  icon `size-8 text-destructive`
- Confirm error is announced to screen readers (`role="alert"` or `aria-live`)

**Loading state verification (GeoLens: `LoadingState` from `@/components/layout/LoadingState`):**
For every async component:
- Intercept the network request and delay it 2s
- Confirm it uses `LoadingState` component (spinner `size-8 animate-spin
  text-muted-foreground`, optional `message` prop)
- If skeleton screens are used instead, confirm skeleton matches loaded content
  dimensions (within 4px — ties to CLS check)

Output: state coverage matrix — component × state × PASS/FAIL/MISSING.
Any MISSING state from the plan spec = plan finding not addressed.

---

### Subagent E — Motion & animation audit
**Goal: confirm all animations follow the plan's spec and respect user preferences**

**`prefers-reduced-motion` compliance:**
```typescript
test('animations respect prefers-reduced-motion', async ({ page }) => {
  // Emulate reduced-motion preference
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(route);
  
  // Check: no CSS animations/transitions running (except opacity: 0→1 is ok)
  const runningAnimations = await page.evaluate(() => {
    const all = document.querySelectorAll('*');
    return Array.from(all).filter(el => {
      const style = window.getComputedStyle(el);
      return style.animationPlayState === 'running' &&
             style.animationName !== 'none';
    }).map(el => el.className);
  });
  
  expect(runningAnimations).toHaveLength(0);
});
```

**Layout-thrashing animation check:**
In changed CSS/Tailwind files, grep for animations that trigger layout:
```bash
git diff -- '*.css' '*.tsx' | grep "^+" | grep -E \
  "animate.*width|animate.*height|animate.*padding|animate.*margin|\
   transition.*width|transition.*height|transition.*padding|transition.*margin"

# Also check for transition-all (DESIGN-GUIDE anti-pattern 5)
git diff -- '*.css' '*.tsx' | grep "^+" | grep "transition-all"
```
Any animation of `width`, `height`, `padding`, `margin`, `top`, `left`, `right`,
or `bottom` is a layout-thrashing animation. Flag as [MOTION-VIOLATION].

Any use of `transition-all` is a [MOTION-VIOLATION] — GeoLens requires targeted
property-list transitions instead.

**Duration compliance:**
Compare each animation's duration against the project standard (DESIGN-GUIDE.md):
- Interactive elements: `duration-200 ease-out` (the project-wide standard)
- `fade-in` animation: `200ms ease-out both` (page transitions)
- `shimmer` animation: `1.5s ease-in-out infinite` (skeleton placeholders)
- UI feedback (hover, active, focus): 100–200ms target
- Any duration > 400ms for UI feedback = [MOTION-VIOLATION]

**Transition standard compliance (GeoLens-specific):**
The project standard for all interactive elements is:
```
transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out
```
Check that new interactive elements follow this pattern. No custom easing tokens
are defined in the project — `ease-out` is the standard. If the plan specifies
custom easing tokens (`--ease-out-quart`, etc.), verify they were actually added
to `frontend/src/index.css` before checking component usage.

**View Transitions verification (if specified in plan):**
```typescript
// Confirm view-transition-name attributes are present on specified elements
const navElement = await page.locator('[style*="view-transition-name: nav"]');
await expect(navElement).toBeVisible();

// Trigger the specified route transition
// Confirm no jarring flash between routes
```

Output: motion compliance matrix — animation × duration × easing × reduced-motion × PASS/FAIL.

---

### Subagent F — Responsiveness & touch verification
**Goal: confirm the layout works at all specified breakpoints and on touch devices**

**Three-viewport screenshot battery:**
Already captured in Phase 1. For each:

Desktop (1440px):
- No horizontal scroll
- No overlapping elements
- All grid/flex layouts as designed

Tablet (768px):
- Responsive grid collapses as expected
- Navigation adapts (hamburger menu, tab bar, or equivalent)
- No text truncation at unexpected points
- Touch targets ≥ 44×44px

Mobile (390px — iPhone 14 Pro viewport):
- Single-column layout where specified
- No content hidden by safe-area violations (check notch, home indicator)
- Tap targets ≥ 44×44px
- Virtual keyboard doesn't obscure active form fields
- Bottom nav/FAB not covered by home indicator area

**Container query verification (if specified in plan):**
```typescript
// Resize component's container (not viewport) to trigger container query
await page.evaluate(() => {
  const container = document.querySelector('.card-container');
  container.style.width = '320px'; // narrow container
});
// Confirm component re-layouts as specified
```

**Safe area inset check:**
```typescript
// iOS-specific: check bottom nav, FABs, fixed footers
const bottomNav = await page.locator('nav[aria-label="bottom navigation"]');
const paddingBottom = await bottomNav.evaluate(el =>
  window.getComputedStyle(el).paddingBottom
);
// Should contain env(safe-area-inset-bottom) — check CSS source
```

**Touch target measurement:**
```typescript
const touchTargets = await page.locator('button, a, [role="button"]').all();
for (const target of touchTargets) {
  const box = await target.boundingBox();
  if (box) {
    // WCAG 2.2 SC 2.5.8 minimum: 24×24px
    expect(box.width).toBeGreaterThanOrEqual(24);
    expect(box.height).toBeGreaterThanOrEqual(24);
    // Log targets below recommended 44×44px as warnings
    if (box.width < 44 || box.height < 44) {
      console.warn(`Small touch target: ${box.width}×${box.height}px`);
    }
  }
}
```

Output: per-viewport PASS/FAIL table. Touch target inventory with sizes.
Flag any viewport where horizontal scroll appears as [LAYOUT-BREAK].

---

## Phase 3 — Score and gate

Collect all 6 subagent outputs and produce the review scorecard:
```
## UX implementation review — [feature]
Plan: [path to plan doc]
Reviewed: [date]
Reviewer: Claude (/ux-review)

## Scorecard

| Category          | Findings in plan | Addressed | Regressions | Score  |
|-------------------|-----------------|-----------|-------------|--------|
| Visual            | N               | N         | N           | PASS/WARN/FAIL |
| Accessibility     | N               | N         | N           | PASS/WARN/FAIL |
| Token compliance  | N               | N         | N           | PASS/WARN/FAIL |
| State coverage    | N               | N         | N           | PASS/WARN/FAIL |
| Motion            | N               | N         | N           | PASS/WARN/FAIL |
| Responsiveness    | N               | N         | N           | PASS/WARN/FAIL |

Overall: PASS / PASS WITH NOTES / FAIL

## Automatic FAIL conditions (any one = FAIL regardless of overall score)
- [ ] Any [LEGAL-RISK] a11y finding still open
- [ ] Any [A11Y-CRITICAL] or [A11Y-HIGH] finding still open
- [ ] Any [VISUAL-REGRESSION] on a route not in the plan's change scope
- [ ] Any [CLS-REGRESSION] (new layout shift introduced)
- [ ] Any [LAYOUT-BREAK] (horizontal scroll at any breakpoint)
- [ ] Test suite failing (Playwright, Jest, or type errors)

## Findings addressed ✓
[List each plan finding ID + status: RESOLVED / PARTIAL / OPEN]

## New issues introduced (not in original plan)
[Any regression or new finding discovered during review, with severity]

## Remaining open items
[Plan findings not yet addressed — with recommendation: block merge / OK for follow-up]

## Scope creep noted
[Files changed outside plan scope — informational only, not blocking]
```

**Scoring logic:**
- PASS: all CRITICAL/HIGH findings addressed, 0 regressions in category
- WARN: all CRITICAL/HIGH addressed, >=1 MEDIUM open or 1 minor regression
- FAIL: any CRITICAL/HIGH open, or any regression in category

**Overall verdict:**
- PASS: all categories PASS or WARN, zero automatic FAIL conditions
- PASS WITH NOTES: one or more WARN, zero automatic FAIL conditions — merge OK,
  open follow-up tickets for MEDIUM items
- FAIL: any category FAIL or any automatic FAIL condition — do not merge, return to developer

---

## Phase 4 — Deliver review artifacts

**1. Post review comment to PR (if GitHub MCP connected):**
```
/ux-review result: [PASS | PASS WITH NOTES | FAIL]

Scorecard: [paste scorecard table]

[If FAIL]: Blocking issues:
- [U0X] [finding description] — still open at [file:line]
  Suggested fix: [one-sentence fix]

[If PASS WITH NOTES]: Follow-up tickets recommended:
- [U0X] [finding description] — MEDIUM, OK to merge, create ticket

Visual regression report: .ux-audit/report/index.html
```

**2. Generate visual diff HTML report:**
```bash
# Run the visual regression tests to generate the HTML report
npx playwright test e2e/ux-capture.ts --reporter=html
# Open the report (defaults to playwright-report/)
npx playwright show-report
```

**3. Write `.ux-audit/review-[feature]-[date].md`:**
Full scorecard, finding-by-finding breakdown, and all subagent raw outputs.
This becomes the paper trail for the implementation decision.

---

## Phase 5 — Archive and update lessons

Regardless of pass/fail outcome, update project memory:

**Update `docs-internal/ux-lessons.md` (create if it doesn't exist):**
```markdown
## [date] — UX review: [feature]

### What worked well
- [patterns that were implemented cleanly and should be reused]

### What caused rework
- [findings that were initially missed or misimplemented]
- [why: misunderstood spec / missing context / wrong API / etc.]

### New patterns established
- [any component, token, or convention established during this cycle
   that should become the default going forward]

### Plan quality notes
- [feedback on the /ux-plan output: was the spec clear? did it miss anything?
   this improves future plan quality]
```

**Close the plan document:**
Append to the plan doc:
```markdown
---
## Review outcome
Status: [PASS | PASS WITH NOTES | FAIL]
Review doc: .ux-audit/review-[feature]-[date].md
Reviewed: [date]
Open follow-ups: [ticket numbers if any]
```

**If FAIL — generate targeted re-plan prompt:**
```
The following findings from ux-plan-[feature]-[date].md remain unresolved:

[list of open CRITICAL/HIGH findings with file:line]

Run `/ux-plan [scope]` scoped to these specific findings to generate
a targeted remediation plan. Suggested scope: [file paths of failing areas]
```

---

## Reference: common reasons reviews fail

These patterns recur — watch for them:

**Skeleton/content dimension mismatch**
The skeleton is built to a static size; the real content is dynamic. Always
use the *measured* loaded content size as the skeleton's target, not a guessed
value.

**Focus rings removed on mobile**
`:focus-visible` is correctly added for desktop but a `@media (hover: none)`
rule removes it on touch devices. Touch users with keyboards (Bluetooth keyboard
+ iPad) are left with no focus indicator.

**`aria-live` region outside the component**
The live region is placed inside a component that unmounts/remounts on state
changes. The browser loses track of the region. Place `aria-live` regions high
in the tree (app layout level) and update their content, never recreate them.

**`prefers-reduced-motion` only in CSS, not in JS animation libs**
`framer-motion` / `@react-spring` have their own APIs for reduced motion that
must be used in addition to the CSS media query. CSS-only coverage misses
JS-driven animations.

**Token added to `index.css` but not used in component**
GeoLens uses `@theme inline` in `frontend/src/index.css` — there is no
`tailwind.config.js`. The token consolidation map is applied to `:root` / `.dark`
blocks in `index.css` but the components still reference the old hardcoded values.
Both the CSS custom properties AND every component usage must be updated.

**Empty state added but not announced**
Empty state renders visually but has no `role="status"` or `aria-live` region,
so screen readers don't announce it when content transitions from loaded → empty.

**Container query breaks in Safari < 16**
Container queries require Safari 16+. If the app supports older Safari, always
include a `@media` query fallback for the same breakpoint.

**`transition-all` slipping through review**
`transition-all` animates width, height, padding, and margin on every state
change, causing layout thrash. GeoLens requires targeted property-list transitions:
`transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out`.

**CSS `var()` in MapLibre paint properties**
MapLibre's WebGL renderer does not evaluate CSS custom properties at runtime.
Map colors must use hex constants from `MAP_COLORS` in `@/lib/map-colors.ts`,
never `var(--primary)` or Tailwind token references.

**Hardcoded Tailwind palette colors for status semantics**
Using `text-green-500` or `bg-red-100` for status states instead of the
centralized maps in `@/lib/status-colors.ts`. Both the component AND its
dark mode variant will be wrong.

**Hardcoded strings instead of i18n keys**
New UI text added directly in JSX (`>Save Changes<`) instead of using the
`t()` function from `react-i18next` with keys in `frontend/src/i18n/locales/`.

---

## Guardrails

**Do not block a merge for:**
- Low-severity findings from the plan explicitly marked as follow-up items
- Style opinions not backed by the plan spec
- Files changed outside scope that don't have regressions
- WCAG AAA criteria (AA is the compliance bar)

**Always block a merge for:**
- Any open [LEGAL-RISK] finding
- Any regression (visual, a11y, layout, CLS) not present before this branch
- Failing Playwright tests
- TypeScript errors introduced in changed files
- Any [MOTION-VIOLATION] where an animation runs unconditionally in
  `prefers-reduced-motion: reduce` mode — this affects real users
- Any use of `transition-all` (DESIGN-GUIDE anti-pattern 5)
- Any use of hardcoded Tailwind palette colors for status semantics
  (must use `@/lib/status-colors.ts` maps)

**Tone of the review output:**
Be precise, not pedantic. Every "fail" comes with the exact file:line and the
exact one-sentence fix. A developer reading the review should be able to fix
every blocking issue without asking a follow-up question.

---

## RELATIONSHIP TO OTHER COMMANDS

- `/ux-plan` — produces the plan this command verifies against. Run plan first, implement, then review.
- `/design-audit` — checks design system conformance and WCAG compliance. This command verifies a specific implementation against a specific plan.
- `/post-impl` — covers code quality broadly. This command focuses on UI/UX implementation correctness.