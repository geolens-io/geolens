---
phase: quick-260326-fzo
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - SUPPORT.md
  - CODE_OF_CONDUCT.md
  - .github/ISSUE_TEMPLATE/config.yml
  - .github/DISCUSSION_TEMPLATE/q-a.yml
  - .github/DISCUSSION_TEMPLATE/ideas.yml
  - frontend/src/components/layout/AppLayout.tsx
  - frontend/src/i18n/locales/en/common.json
  - frontend/src/i18n/locales/fr/common.json
  - frontend/src/i18n/locales/es/common.json
  - frontend/src/i18n/locales/de/common.json
  - .planning/quick/260326-fzo-how-should-we-handle-support-and-discuss/260326-fzo-FINDINGS.md
autonomous: true
requirements: [SUPPORT-STRATEGY, REPO-CONFIG, IN-APP-HELP]

must_haves:
  truths:
    - "SUPPORT.md clearly routes users to Discussions for questions and Issues for bugs"
    - "SUPPORT.md delineates community (best-effort) vs enterprise (SLA) support tiers"
    - "CODE_OF_CONDUCT.md exists with Contributor Covenant v2.1"
    - "Issue template chooser directs questions to Discussions Q&A and ideas to Discussions Ideas"
    - "Discussion templates exist for Q&A and Ideas categories with structured forms"
    - "App footer shows a Community link pointing to GitHub Discussions"
    - "Community link is i18n-translated in all 4 locales"
    - "Strategy doc captures rationale and recommendations"
  artifacts:
    - path: "SUPPORT.md"
      provides: "Support routing guide for users"
    - path: "CODE_OF_CONDUCT.md"
      provides: "Contributor Covenant v2.1"
    - path: ".github/ISSUE_TEMPLATE/config.yml"
      provides: "Template chooser with Discussion links"
    - path: ".github/DISCUSSION_TEMPLATE/q-a.yml"
      provides: "Structured Q&A discussion form"
    - path: ".github/DISCUSSION_TEMPLATE/ideas.yml"
      provides: "Structured Ideas discussion form"
    - path: "frontend/src/components/layout/AppLayout.tsx"
      provides: "Footer with Community link"
    - path: ".planning/quick/260326-fzo-how-should-we-handle-support-and-discuss/260326-fzo-FINDINGS.md"
      provides: "Strategy document with rationale"
  key_links:
    - from: "AppLayout.tsx footer"
      to: "GitHub Discussions URL"
      via: "anchor tag with i18n label"
      pattern: "discussions.*community"
    - from: ".github/ISSUE_TEMPLATE/config.yml"
      to: "GitHub Discussions categories"
      via: "contact_links url fields"
      pattern: "discussions/categories"
---

<objective>
Configure GitHub community infrastructure and in-app help link for GeoLens public release.

Purpose: Route users to the right support channels (Discussions for questions, Issues for bugs, enterprise contact for SLA support) and signal project maturity with standard open-source governance files.

Output: SUPPORT.md, CODE_OF_CONDUCT.md, discussion templates, updated issue template config, footer help link, strategy doc.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260326-fzo-how-should-we-handle-support-and-discuss/260326-fzo-CONTEXT.md
@.planning/quick/260326-fzo-how-should-we-handle-support-and-discuss/260326-fzo-RESEARCH.md
@frontend/src/components/layout/AppLayout.tsx
@frontend/src/i18n/locales/en/common.json
@.github/ISSUE_TEMPLATE/config.yml
@.github/CONTRIBUTING.md

<interfaces>
<!-- Current footer i18n key structure (all 4 locales) -->
"footer": {
  "poweredBy": "Powered by GeoLens"
}

<!-- AppLayout uses -->
const GEOLENS_GITHUB_URL = 'https://github.com/geolens-io/geolens';
t('footer.poweredBy')

<!-- Existing config.yml -->
blank_issues_enabled: true
contact_links:
  - name: Discussions
    url: https://github.com/geolens-io/geolens/discussions
    about: Ask questions, share ideas, or get help from the community
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create SUPPORT.md, CODE_OF_CONDUCT.md, and update issue template config</name>
  <files>SUPPORT.md, CODE_OF_CONDUCT.md, .github/ISSUE_TEMPLATE/config.yml, .github/DISCUSSION_TEMPLATE/q-a.yml, .github/DISCUSSION_TEMPLATE/ideas.yml</files>
  <action>
    **SUPPORT.md** (repo root): Create with these sections:
    1. **Getting Help** — For questions and how-to help, use GitHub Discussions Q&A category. For bug reports, use GitHub Issues with the bug report template. Do NOT open issues for general questions.
    2. **Community Support** — Best-effort, community-driven. No guaranteed response times. Search existing discussions before posting.
    3. **Enterprise Support** — For organizations needing SLA-backed support, priority response, and private channels, contact enterprise@geolens.io (or link to future enterprise page). Includes: guaranteed response times, private Slack/email channel, upgrade assistance, security patching guidance.
    4. **Security Vulnerabilities** — Do NOT report publicly. Email security@geolens.io. (Reference existing CONTRIBUTING.md security section for consistency.)

    **CODE_OF_CONDUCT.md** (repo root): Use Contributor Covenant v2.1 verbatim. Set enforcement contact to conduct@geolens.io. Include standard sections: Our Pledge, Our Standards, Enforcement Responsibilities, Scope, Enforcement, Enforcement Guidelines (Correction, Warning, Temporary Ban, Permanent Ban), Attribution.

    **.github/ISSUE_TEMPLATE/config.yml**: Replace existing content with:
    - `blank_issues_enabled: false` (force template usage to reduce low-quality submissions)
    - contact_links:
      1. "Ask a Question" -> `https://github.com/geolens-io/geolens/discussions/categories/q-a` with about: "Get help from the community — not for bug reports"
      2. "Share an Idea" -> `https://github.com/geolens-io/geolens/discussions/categories/ideas` with about: "Suggest features or discuss enhancements before opening an issue"

    **.github/DISCUSSION_TEMPLATE/q-a.yml**: Create directory and file. GitHub Discussion form template with:
    - title: "Q&A"
    - labels: [] (discussions don't use labels, but the form needs body field)
    - body fields: textarea for "Question" (required, description: "What do you need help with?"), textarea for "What I've tried" (optional), input for "GeoLens version" (optional), dropdown for "Deployment method" with options: Docker Compose, Kubernetes/Helm, AWS AMI, Other

    **.github/DISCUSSION_TEMPLATE/ideas.yml**: Form template with:
    - title: "Ideas"
    - body fields: textarea for "Idea" (required, description: "Describe your feature idea or enhancement"), textarea for "Use case" (required, description: "What problem does this solve?"), textarea for "Alternatives considered" (optional)
  </action>
  <verify>
    <automated>test -f SUPPORT.md && test -f CODE_OF_CONDUCT.md && test -f .github/ISSUE_TEMPLATE/config.yml && test -f .github/DISCUSSION_TEMPLATE/q-a.yml && test -f .github/DISCUSSION_TEMPLATE/ideas.yml && grep -q "enterprise" SUPPORT.md && grep -q "Contributor Covenant" CODE_OF_CONDUCT.md && grep -q "blank_issues_enabled: false" .github/ISSUE_TEMPLATE/config.yml && echo "PASS" || echo "FAIL"</automated>
  </verify>
  <done>SUPPORT.md routes users to correct channels with clear community/enterprise boundary. CODE_OF_CONDUCT.md has Contributor Covenant v2.1. Issue template config disables blank issues and redirects questions/ideas to Discussions. Discussion templates provide structured forms for Q&A and Ideas categories.</done>
</task>

<task type="auto">
  <name>Task 2: Add Community link to app footer with i18n</name>
  <files>frontend/src/components/layout/AppLayout.tsx, frontend/src/i18n/locales/en/common.json, frontend/src/i18n/locales/fr/common.json, frontend/src/i18n/locales/es/common.json, frontend/src/i18n/locales/de/common.json</files>
  <action>
    **AppLayout.tsx**: Add a constant `GEOLENS_DISCUSSIONS_URL = 'https://github.com/geolens-io/geolens/discussions'`. In the footer, after the existing "Powered by GeoLens" link, add a middle-dot separator (`\u00B7` or ` · `) and a second link:
    ```
    <span className="mx-1.5">·</span>
    <a href={GEOLENS_DISCUSSIONS_URL} target="_blank" rel="noopener noreferrer"
       className="hover:text-foreground transition-colors">
      {t('footer.community')}
    </a>
    ```
    Wrap both links in a flex container or span so they sit inline naturally.

    **i18n keys**: Add `"community": "Community"` to the `"footer"` object in all 4 locale files:
    - en: `"community": "Community"`
    - fr: `"community": "Communaut\u00e9"`
    - es: `"community": "Comunidad"`
    - de: `"community": "Community"` (commonly used in German tech contexts as-is)
  </action>
  <verify>
    <automated>cd frontend && grep -q "GEOLENS_DISCUSSIONS_URL" src/components/layout/AppLayout.tsx && grep -q "footer.community" src/components/layout/AppLayout.tsx && grep -q '"community"' src/i18n/locales/en/common.json && grep -q '"community"' src/i18n/locales/fr/common.json && grep -q '"community"' src/i18n/locales/es/common.json && grep -q '"community"' src/i18n/locales/de/common.json && echo "PASS" || echo "FAIL"</automated>
  </verify>
  <done>Footer displays "Powered by GeoLens · Community" with the Community link pointing to GitHub Discussions. All 4 locales have the translated key.</done>
</task>

<task type="auto">
  <name>Task 3: Write strategy FINDINGS.md</name>
  <files>.planning/quick/260326-fzo-how-should-we-handle-support-and-discuss/260326-fzo-FINDINGS.md</files>
  <action>
    Create the strategy document summarizing decisions, rationale, and setup instructions. Structure:

    1. **Overview** — GeoLens uses GitHub as the single community platform: Discussions for questions/ideas/announcements, Issues for bugs/feature requests. No separate Discord or forum.

    2. **Channel Routing** — Table showing: Question -> Discussions Q&A, Bug -> Issues (bug template), Feature request -> Issues (feature template) OR Discussions Ideas, Announcement -> Discussions Announcements (maintainer-only), Show & Tell -> Discussions Show & Tell.

    3. **Support Tiers** — Community: GitHub Discussions + Issues, best-effort, no SLA. Enterprise: private Slack/email, guaranteed response times, upgrade assistance, security patching. Contact: enterprise@geolens.io.

    4. **Discussion Categories** — List the 5 recommended categories (Announcements, Q&A, Ideas, Show & Tell, General) with format type and purpose. Note: these must be created manually in GitHub repo Settings > Discussions.

    5. **Repo Configuration Delivered** — List of files created/updated with brief description.

    6. **Post-Deployment Checklist** — Manual steps the maintainer must do:
       - Enable Discussions in GitHub repo Settings > General > Features
       - Create the 5 discussion categories (Announcements as announcement format, Q&A as question format, others as open-ended)
       - Pin a welcome post in Announcements
       - Pin a "How to get help" post in General
       - Verify SUPPORT.md renders on repo page

    7. **Future Considerations** — Saved searches/auto-labels for triage, GitHub Actions bot for stale discussions, community health metrics dashboard.
  </action>
  <verify>
    <automated>test -f .planning/quick/260326-fzo-how-should-we-handle-support-and-discuss/260326-fzo-FINDINGS.md && grep -q "Channel Routing" .planning/quick/260326-fzo-how-should-we-handle-support-and-discuss/260326-fzo-FINDINGS.md && grep -q "Post-Deployment" .planning/quick/260326-fzo-how-should-we-handle-support-and-discuss/260326-fzo-FINDINGS.md && echo "PASS" || echo "FAIL"</automated>
  </verify>
  <done>Strategy document captures all decisions, channel routing, support tier boundaries, and a post-deployment checklist for manual GitHub configuration steps.</done>
</task>

</tasks>

<verification>
- SUPPORT.md exists at repo root with community/enterprise support tiers
- CODE_OF_CONDUCT.md exists at repo root with Contributor Covenant v2.1
- .github/ISSUE_TEMPLATE/config.yml disables blank issues and links to Discussion categories
- .github/DISCUSSION_TEMPLATE/ contains q-a.yml and ideas.yml form templates
- AppLayout footer shows "Powered by GeoLens · Community" with correct link
- All 4 i18n locale files have footer.community key
- FINDINGS.md captures strategy and post-deployment checklist
</verification>

<success_criteria>
Users visiting the GitHub repo see SUPPORT.md guidance and CODE_OF_CONDUCT.md. Issue template chooser redirects questions to Discussions Q&A and ideas to Discussions Ideas. App footer provides a visible Community link to GitHub Discussions. Strategy doc provides maintainer with a clear post-deployment checklist for enabling and seeding Discussion categories.
</success_criteria>

<output>
After completion, create `.planning/quick/260326-fzo-how-should-we-handle-support-and-discuss/260326-fzo-SUMMARY.md`
</output>
