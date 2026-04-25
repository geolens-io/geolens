# Pitfalls Research

**Domain:** Marketing site for open-core GIS data catalog targeting enterprise/government buyers
**Researched:** 2026-04-03
**Confidence:** HIGH (messaging/conversion/SEO), MEDIUM (gov accessibility compliance specifics)

---

## Critical Pitfalls

### Pitfall 1: Hero Section That Describes the Technology Instead of the Outcome

**What goes wrong:**
The hero headline leads with what GeoLens _is_ ("A PostGIS-native GIS data catalog") instead of what the user _gets_ ("Find any dataset in seconds. Map it. Export it."). Technical visitors understand the jargon; non-technical IT managers and procurement officers who control the budget do not. The page fails both audiences simultaneously.

**Why it happens:**
Builders write for themselves. The team that built a PostGIS-native catalog wants credit for that architectural choice. But the buyer persona who signs off on procurement does not care about PostGIS — they care whether their GIS analysts will stop complaining.

**How to avoid:**
Lead with the outcome for the primary persona (GIS analyst: "Find any dataset in seconds"), then layer in the technical credibility signal for the secondary persona (IT manager: "Self-hosted. Docker Compose. Apache 2.0."). The hero headline should pass the "five-second test" — a stranger who has never heard of GeoLens should understand what problem it solves after five seconds on the page.

**Warning signs:**
- Hero headline contains words like "PostGIS-native," "catalog," or "RBAC" without a plain-English follow-up
- The subheadline describes architecture rather than a user benefit
- The first CTA is "Read the Docs" rather than "Get Started" or a live demo

**Phase to address:**
Copywriting phase — before any design or development work. Lock the headline and value proposition first, then design around it.

---

### Pitfall 2: Dual CTA Competition That Kills Both Conversions

**What goes wrong:**
Placing "Get Started (Community)" and "Contact for Enterprise" as equal-weight primary CTAs on the hero causes visitors to do neither. Multiple competing CTAs dilute attention. Research from B2B SaaS conversion studies shows single-CTA pages convert 13.5% vs. 10.5% for multi-CTA pages — a meaningful gap at the top of funnel.

**Why it happens:**
The team wants to serve both audiences simultaneously. The impulse is correct (there are two paths) but the execution is wrong. Equal visual weight implies neither is the default path.

**How to avoid:**
Give the community self-serve path (`docker compose up`) primary visual weight (filled button, prominent position). Give the enterprise contact path secondary weight (ghost/outline button, positioned after). Most visitors are GIS analysts evaluating for themselves; treat that as the default. Enterprise buyers who need the contact path will find it regardless of button styling.

**Warning signs:**
- Two filled primary buttons side-by-side in the hero
- Enterprise CTA above or before the self-serve CTA
- The editions comparison page pushes enterprise harder than community

**Phase to address:**
Design phase — enforce button hierarchy in the design system before implementation.

---

### Pitfall 3: Feature Comparison Table That Undermines the Community Edition

**What goes wrong:**
A community-vs-enterprise comparison table with a long column of red X marks in the community column signals to GIS analysts that the free version is deliberately crippled. This is the opposite of what open-core projects need: community adoption drives enterprise discovery. If community feels like a demo, analysts will not deploy it and their IT managers will never see the enterprise upsell.

**Why it happens:**
The table format is borrowed from SaaS competitors without considering the different incentive structure of open-core. Open Core Ventures explicitly warns: use comparison tables against _competitors_, not against your open-source tier.

**How to avoid:**
Frame the community edition as genuinely complete for the core use case (search, preview, export, RBAC, OGC APIs — all in). Frame enterprise as "everything in Community, plus [specific enterprise-only capabilities]" — SAML SSO, audit export, multi-tenant branding. Never show a feature the community version lacks without a clear explanation of _why_ that feature is enterprise-only (e.g., "SAML SSO requires enterprise identity provider integration"). Avoid the checkbox table. Use a brief prose list of enterprise additions instead.

**Warning signs:**
- More than 30% of community column cells are negative/absent
- The comparison table lists features like "Map Preview" or "Export" as enterprise-only
- Community column has no checkmark for any security feature

**Phase to address:**
Editions page design — requires product decisions on community/enterprise boundary before implementation.

---

### Pitfall 4: Missing Trust Signals for Government Procurement

**What goes wrong:**
Government IT managers and procurement officers face a lengthy approval chain. A marketing site with no compliance signals, no mention of security practices, and no indication of organizational stability causes them to deprioritize evaluation in favor of known vendors. Unlike private enterprise buyers, government buyers are often required to document due diligence — a site that doesn't make that easy fails them.

**Why it happens:**
Technical founders build for technical evaluators (GIS analysts) and forget the parallel procurement track. The analyst may love the product; the contracting officer may reject it for lack of documentation.

**How to avoid:**
Surface these signals on the homepage and/or a dedicated compliance/security page:
- Apache 2.0 license with a direct link to the license text
- OGC API conformance badges (OGC API – Records, OGC API – Features)
- Self-hosted on-premise deployment (data never leaves their network)
- WCAG 2.1 AA accessibility conformance (required in Section 508 procurements and ADA Title II)
- RBAC, audit logging, non-root containers, and Trivy CI scanning — these are procurement checklist items
- A VPAT (Voluntary Product Accessibility Template) or link to one, even a draft, signals seriousness to federal buyers
- GitHub link to the public repository (demonstrated maintenance cadence matters)

**Warning signs:**
- Homepage has no mention of "on-premise," "self-hosted," or "data sovereignty"
- No mention of open standards (OGC) anywhere in the value proposition
- Security and compliance are buried in a footer link or absent entirely

**Phase to address:**
Trust signals phase — build a compliance/security section into the site structure from the start, not retrofitted.

---

### Pitfall 5: SEO Neglect on a Static Site (Assuming Fast = Optimized)

**What goes wrong:**
Astro produces fast static HTML, but speed is not SEO. Common failures: pages share identical `<title>` and meta description tags (Astro doesn't auto-generate unique ones), Open Graph images are the same site-wide or missing entirely, canonical tags are absent causing potential duplicate content, and there is no JSON-LD structured data to signal software product metadata to search engines.

**Why it happens:**
Developers treat Astro's fast Lighthouse score as proof of SEO health. Lighthouse measures performance, not search appearance. A page can score 100 on Lighthouse and still share a title with five other pages.

**How to avoid:**
- Create a `BaseHead.astro` component that accepts `title`, `description`, `ogImage`, and `canonical` props — enforce their use on every page layout
- Generate page-specific OG images at build time (use `@vercel/og` or `astro-og-canvas`)
- Add JSON-LD `SoftwareApplication` schema to the homepage
- Submit `sitemap.xml` to Google Search Console at launch
- Use the `astro-seo` integration (`github.com/jonasmerlin/astro-seo`) rather than hand-rolling meta tags
- Ensure `robots.txt` is present and correct

**Warning signs:**
- Running `curl -s https://getgeolens.com | grep "<title>"` returns the same result as any other page
- Social sharing previews show no image or the site logo on every page
- Google Search Console shows "Duplicate without user-selected canonical" for multiple pages

**Phase to address:**
SEO fundamentals phase — implement BaseHead component and sitemap before any content pages are added.

---

### Pitfall 6: WCAG / Section 508 Treated as Optional

**What goes wrong:**
Government buyers (federal, state, local) are legally required to procure accessible software under Section 508 of the Rehabilitation Act (federal) and ADA Title II (state/local, enforcement deadline April 24, 2026 for large jurisdictions). A marketing site that fails basic accessibility checks — keyboard navigation, color contrast, missing alt text, no skip links — signals that the product itself is likely inaccessible. Agencies cannot award contracts to vendors whose tools fail WCAG 2.1 AA without documented exceptions.

**Why it happens:**
Accessibility is treated as a launch-blocker only when a government buyer explicitly raises it. By then, it's already a disqualifier.

**How to avoid:**
- Target WCAG 2.1 AA from the first design mockup, not as a retrofit
- Run automated audits (Axe, Lighthouse accessibility) in CI before launch
- Test keyboard navigation manually — every CTA, form field, and navigation item must be reachable without a mouse
- Ensure color contrast ratio of at least 4.5:1 for normal text (emerald accent on white must be verified — emerald-600 on white is borderline)
- Add `alt` text to all product screenshots
- Provide a contact email as a fallback if the enterprise contact form fails (a requirement under some Section 508 interpretations)
- Prepare a draft VPAT document, even if incomplete — federal buyers expect to see one in the procurement package

**Warning signs:**
- Lighthouse accessibility score below 95
- Any CTA button reachable only with a mouse
- Product screenshots with no alt text
- Enterprise contact form with no accessible error messages

**Phase to address:**
Design system phase — establish contrast ratios and interactive element sizing before building components.

---

### Pitfall 7: Messaging Collapse Under Two-Persona Conflict

**What goes wrong:**
GIS analysts (discover, evaluate) and IT managers (approve, procure) care about completely different things. Copy that tries to speak to both simultaneously ends up resonating with neither. An analyst cares about search quality, export formats, and map preview. An IT manager cares about licensing, deployment model, security posture, and support. A single page trying to satisfy both produces bloated, unfocused copy.

**Why it happens:**
There is no clear persona hierarchy. The team writes "for users" without specifying which user is on each page.

**How to avoid:**
Establish a persona hierarchy per page section. The homepage hero addresses the analyst's pain point first (discovery speed) then layers in the IT manager's trust signals (self-hosted, Apache 2.0, OGC standards). The enterprise contact page flips this — IT manager concerns first, analyst benefits as supporting evidence. The features page can be analyst-primary with technical specifics. The editions/comparison page should be IT manager-primary with licensing and compliance framing.

**Warning signs:**
- The homepage hero mentions Docker Compose before explaining what the tool does
- The enterprise contact page talks about search relevance ranking before mentioning RBAC or audit logging
- Copywriters are writing "for developers" across every page

**Phase to address:**
Content strategy phase — persona mapping before copywriting.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Hardcode all meta tags per page manually | Fast to ship first pages | Every new page requires manual SEO audit; mismatches guaranteed | Never — use a BaseHead component |
| Use same OG image site-wide | Zero build complexity | Reduced click-through from social sharing; same image on every URL looks lazy | Never — generate page-specific OG images at build |
| Ship without VPAT documentation | Faster to launch | Disqualified from federal RFPs; no recovery path without retroactive audit | Only if no government buyers targeted in first 6 months |
| Contact form without email fallback | Simpler form implementation | Section 508 non-compliance; enterprise buyers with blocked JS cannot convert | Never — always include a plain mailto: fallback |
| "Contact for Pricing" with no price signals | Avoids commitment | Enterprise buyers deprioritize evaluation when cost is completely opaque; expect $0 or astronomical | Acceptable in MVP if a rough ballpark is in the sales email response |
| Identical mobile layout to desktop (no responsive audit) | Faster development | IT managers reviewing from mobile during travel see broken layouts; credibility hit | Never — test on mobile before launch |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Enterprise contact form | Using a JS-only form library that fails when scripts are blocked by government network policies | Use a server-side form handler or a form service (Formspree, Basin) that degrades to a plain POST; always include a mailto: fallback |
| Analytics (Plausible/Fathom) | Blocking page load due to script errors when ad blockers strip the analytics tag | Use privacy-first analytics (Plausible) that degrades gracefully; never make it a render-blocking dependency |
| GitHub stars widget | Stars widget fails to load in air-gapped government evaluation environments, breaking layout | Use a static star count image or pre-rendered count with a fallback number; don't depend on GitHub API at render time |
| OG image generation at build | `@vercel/og` fails in non-Vercel CI environments without explicit Node version pinning | Test OG image build in the same CI environment used for deployment; pin Node version |
| Sitemap and robots.txt | Astro does not generate these by default; forgetting them means Google cannot discover new pages | Add `@astrojs/sitemap` to the Astro config and verify `robots.txt` is in `/public` before launch |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Large uncompressed product screenshots | Slow load on enterprise VPN connections (often throttled) | Run screenshots through `squoosh` or `sharp`; use `<picture>` with WebP + AVIF; Astro's `<Image>` component handles this automatically | Immediately on first launch; government networks are often slow |
| Self-hosted fonts loaded synchronously | FOUT (flash of unstyled text) on slow connections | Use `font-display: swap`; preload font files in `<head>`; consider system font fallback stack while Inter loads | Any connection slower than 50 Mbps |
| Unoptimized video demos or GIF previews | 10-20MB page weight; kills Lighthouse score | Replace animated GIFs with `<video autoplay loop muted>` with WebM + MP4; keep under 2MB | Any mobile connection |
| Third-party scripts (chat widget, Hubspot) blocking render | LCP > 3s; Lighthouse score drop | Load third-party scripts with `async` or `defer`; move chat widgets to user interaction trigger | First day after adding a sales chat widget |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Enterprise contact form with no rate limiting | Spam flooding the sales inbox from bot submissions | Add honeypot field + server-side rate limiting; use a form service with built-in spam protection |
| Exposing team member email addresses in plain text on the site | Harvested for spam; government buyers may flag as unprofessional | Use contact forms; if email must appear, use a role address (hello@getgeolens.com) and obfuscate |
| No HTTPS enforcement | Government procurement scanners flag HTTP endpoints as non-compliant | Enforce HTTPS with HSTS header; configure at CDN/host level before launch |
| Inline `<script>` tags without CSP header | XSS attack surface; some government network proxies block pages with inline scripts | Set `Content-Security-Policy` header; Astro's static output makes CSP practical since there's minimal dynamic JS |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| "Contact for Enterprise" with no information about what enterprise includes | IT managers cannot build a business case internally without knowing what they're buying | Show enterprise feature list before the CTA; let buyers self-qualify |
| Quickstart that starts with environment prerequisites | Developers bounce before reaching `docker compose up` | Lead with the compose command; put prerequisites in a collapsible or footnote |
| Product screenshots showing empty/placeholder data | Makes the product look unused or unproven | Use realistic sample data (park boundaries, census tracts, road networks) that demonstrate actual GIS use cases |
| Mobile navigation with no hamburger state management | Government IT managers on phones during travel cannot navigate between pages | Test menu open/close on iOS Safari and Android Chrome specifically before launch |
| Dark mode implementation with FOUC | Flash of wrong theme on page load destroys first impression | Use the same inline theme-detection script pattern already in GeoLens (`index.html` FOUC script); apply it to the marketing site |
| Enterprise CTA that opens a new tab to a Google Form | Signals lack of investment; gov buyers flag third-party form services as data handling concerns | Use a first-party form on the same domain with a clear privacy/data handling note |

---

## "Looks Done But Isn't" Checklist

- [ ] **SEO:** Every page has a unique `<title>` and `<meta name="description">` — verify by checking page source of homepage, features, and editions pages
- [ ] **OG Images:** Sharing any page URL to Slack/LinkedIn shows a distinct image, not the generic site logo — verify with opengraph.xyz
- [ ] **Sitemap:** `https://getgeolens.com/sitemap.xml` returns valid XML listing all pages — verify before launch
- [ ] **Canonical:** Every page has a `<link rel="canonical">` pointing to its own URL — verify with browser developer tools
- [ ] **Accessibility:** Lighthouse accessibility score >= 95 on desktop AND mobile — run before launch
- [ ] **Keyboard navigation:** Tab through the homepage without touching mouse — every CTA and nav item must be reachable and visually focused
- [ ] **Color contrast:** Emerald accent color on white background meets 4.5:1 ratio — verify with WebAIM contrast checker (emerald-600 is marginal; use emerald-700 if needed)
- [ ] **Mobile layout:** Homepage, features page, and enterprise contact page render correctly at 375px width — test on real device, not just browser resize
- [ ] **Contact form fallback:** The enterprise contact page shows a mailto: email address in addition to the form — confirms accessibility for JS-blocked environments
- [ ] **Alt text:** Every product screenshot has descriptive alt text — run `axe` audit
- [ ] **Dark mode:** Page does not flash white then go dark on page load — test by hard refreshing with dark mode enabled in OS
- [ ] **HTTPS:** Site redirects HTTP to HTTPS; no mixed content warnings in browser console
- [ ] **VPAT:** A VPAT document (even a draft) is linked from the site or available on request — confirmed with sales response template

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Hero messaging misses both personas | LOW | A/B test two headline variants; copy is the cheapest asset to change |
| Dual CTA competition discovered post-launch | LOW | Restyle one button to ghost variant; swap order if needed; no code changes required |
| SEO meta tags missing or duplicated | MEDIUM | Requires a BaseHead refactor across all pages; Google re-crawl takes 2-4 weeks after fix |
| Missing sitemap at launch | LOW | Add `@astrojs/sitemap`, redeploy, submit to Search Console; takes 1-2 weeks to index |
| Accessibility failures discovered in government evaluation | HIGH | Full accessibility audit + remediation; government evaluations move to competitor while work happens; avoid by auditing before launch |
| Product screenshots with placeholder/fake data | MEDIUM | Requires new screenshot session with realistic data; design integration; retesting |
| VPAT missing from federal RFP response | HIGH | Cannot retroactively qualify for that RFP cycle; requires creating VPAT before next solicitation period |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Hero messaging (outcome vs. technology) | Content strategy / copywriting | 5-second test with a non-GIS person before design handoff |
| Dual CTA competition | Design system / component design | Visual hierarchy review: one filled button, one ghost button in hero |
| Community edition undermined by comparison table | Editions page design | Review: community column has no unnecessary negatives for core features |
| Missing gov trust signals | Homepage and trust/compliance section | Security/compliance checklist mapped to page sections before implementation |
| SEO neglect (missing unique meta tags, OG images) | SEO fundamentals phase | Automated check of `<title>` uniqueness across all pages at build time |
| WCAG / Section 508 non-compliance | Design system phase | Axe CI scan; manual keyboard test; contrast ratio audit on design mockups |
| Two-persona messaging collapse | Content strategy phase | Persona map assigned to each page section before copywriting begins |
| Product screenshots with empty data | Asset production phase | Screenshot checklist: realistic GIS datasets, not Lorem Ipsum |
| Enterprise contact form without fallback | Forms implementation phase | Test with JavaScript disabled; confirm mailto: fallback visible |
| Dark mode FOUC | Theme implementation phase | Hard-refresh test with OS dark mode enabled |

---

## Sources

- [TODO Group: Marketing Open Source Projects](https://todogroup.org/resources/guides/marketing-open-source-projects/)
- [Open Core Ventures: Your Pricing Page Should Be Boring and Predictable](https://www.opencoreventures.com/blog/your-pricing-page-should-be-boring-and-predictable)
- [Open Core Ventures: Open Core Is a Misunderstood Business Model](https://www.opencoreventures.com/blog/open-core-is-a-misunderstood-business-model)
- [Open Core Ventures: A Standard Pricing Model for Open Core](https://www.opencoreventures.com/blog/a-standard-pricing-model-for-open-core)
- [Teleport: SaaS vs Open Core Business Model](https://goteleport.com/blog/open-core-vs-saas-business-model/)
- [Section508.gov: Sell Accessible Products and Services](https://www.section508.gov/sell/)
- [Level Access: Section 508 Compliance Guide 2026](https://www.levelaccess.com/compliance-overview/section-508-compliance/)
- [Accessibility.Works: ADA Title II Compliance Deadlines](https://www.accessibility.works/blog/ada-title-ii-2-compliance-standards-requirements-states-cities-towns/)
- [DEV Community: 5 SEO Mistakes Developers Still Make in 2025](https://dev.to/bakhat_yar_seo/5-seo-mistakes-developers-still-make-in-2025-4j9k)
- [Astro SEO Complete Guide](https://eastondev.com/blog/en/posts/dev/20251202-astro-seo-complete-guide/)
- [astro-seo integration](https://github.com/jonasmerlin/astro-seo)
- [Altitude Marketing: Marketing Geospatial Technology Companies](https://altitudemarketing.com/blog/marketing-geospatial-technology-companies/)
- [Scarf Blog: Selling Open Source 101](https://about.scarf.sh/post/selling-open-source-101-guide-for-sales-and-marketing-teams)
- [Actual Tech Media: Enterprise Tech Buyer Journey](https://www.actualtechmedia.com/blog/the-enterprise-tech-buyers-journey-a-step-by-step-guide-to-optimize-your-process/)
- [SaaS Hero: B2B SaaS Conversion Benchmarks 2026](https://www.saashero.net/content/2026-b2b-saas-conversion-benchmarks/)

---
*Pitfalls research for: getgeolens.com marketing site — open-core GIS catalog targeting enterprise/government*
*Researched: 2026-04-03*
