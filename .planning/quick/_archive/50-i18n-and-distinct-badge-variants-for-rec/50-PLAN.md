---
phase: quick-50
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/search/DatasetCard.tsx
  - frontend/src/i18n/locales/en/search.json
  - frontend/src/i18n/locales/es/search.json
  - frontend/src/i18n/locales/fr/search.json
  - frontend/src/i18n/locales/de/search.json
autonomous: true
requirements: [QUICK-50]

must_haves:
  truths:
    - "Draft badge label comes from i18n t() not hardcoded string"
    - "Draft badge is amber/warning colored"
    - "Archived badge is secondary (neutral) styled"
    - "Deprecated badge is outline/muted styled"
  artifacts:
    - path: "frontend/src/components/search/DatasetCard.tsx"
      provides: "Updated badge rendering with per-status variant and i18n label"
    - path: "frontend/src/i18n/locales/en/search.json"
      provides: "card.status.draft, card.status.archived, card.status.deprecated translation keys"
  key_links:
    - from: "DatasetCard.tsx"
      to: "search.json card.status.*"
      via: "t('card.status.draft') etc"
      pattern: "t\\('card\\.status\\."
---

<objective>
Fix two small issues in DatasetCard.tsx record_status badge: replace the hardcoded 'Draft' string with i18n translation, and apply distinct visual variants for draft (amber), archived (secondary/neutral), and deprecated (outline/muted).

Purpose: Consistency with the project's i18n pattern and improved status legibility.
Output: Updated DatasetCard.tsx + translation keys in all four locale files.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@frontend/src/components/search/DatasetCard.tsx
@frontend/src/i18n/locales/en/search.json
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add record_status translation keys to all locale files</name>
  <files>
    frontend/src/i18n/locales/en/search.json,
    frontend/src/i18n/locales/es/search.json,
    frontend/src/i18n/locales/fr/search.json,
    frontend/src/i18n/locales/de/search.json
  </files>
  <action>
Add a `status` sub-key to the `card` object in each locale file with keys for the three non-published states.

en:
```json
"status": {
  "draft": "Draft",
  "archived": "Archived",
  "deprecated": "Deprecated"
}
```

es:
```json
"status": {
  "draft": "Borrador",
  "archived": "Archivado",
  "deprecated": "Obsoleto"
}
```

fr:
```json
"status": {
  "draft": "Brouillon",
  "archived": "Archivé",
  "deprecated": "Obsolète"
}
```

de:
```json
"status": {
  "draft": "Entwurf",
  "archived": "Archiviert",
  "deprecated": "Veraltet"
}
```

Insert as the last key inside the `card` object in each file (before the closing `}`).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && node -e "['en','es','fr','de'].forEach(l => { const d = require('./frontend/src/i18n/locales/'+l+'/search.json'); console.log(l, d.card.status); })"</automated>
  </verify>
  <done>All four locale files have card.status.draft, card.status.archived, card.status.deprecated keys with locale-appropriate strings.</done>
</task>

<task type="auto">
  <name>Task 2: Update DatasetCard.tsx badge with i18n labels and distinct variants</name>
  <files>frontend/src/components/search/DatasetCard.tsx</files>
  <action>
Replace the current record_status badge block (lines 55-59) with a per-status lookup that uses i18n labels and distinct visual styles. Do NOT use a `variant` prop alone for the amber styling — the Badge component has no built-in amber variant, so use `className` overrides as the existing code already does for amber.

Replace:
```tsx
{recordStatus && recordStatus !== 'published' && (
  <Badge variant="outline" className="text-xs border-amber-500/50 text-amber-600 dark:text-amber-400">
    {recordStatus === 'draft' ? 'Draft' : recordStatus.charAt(0).toUpperCase() + recordStatus.slice(1)}
  </Badge>
)}
```

With:
```tsx
{recordStatus && recordStatus !== 'published' && (() => {
  const statusStyles: Record<string, string> = {
    draft: 'text-xs border-amber-500/50 text-amber-600 dark:text-amber-400',
    archived: 'text-xs',
    deprecated: 'text-xs text-muted-foreground',
  };
  const statusVariants: Record<string, 'outline' | 'secondary'> = {
    draft: 'outline',
    archived: 'secondary',
    deprecated: 'outline',
  };
  const label = t(`card.status.${recordStatus}`, {
    defaultValue: recordStatus.charAt(0).toUpperCase() + recordStatus.slice(1),
  });
  return (
    <Badge
      variant={statusVariants[recordStatus] ?? 'outline'}
      className={statusStyles[recordStatus] ?? 'text-xs'}
    >
      {label}
    </Badge>
  );
})()}
```

This pattern:
- draft: amber outline (same visual as before, now i18n)
- archived: secondary (neutral filled badge — subdued)
- deprecated: outline with muted text (de-emphasised)
- any unknown future status: falls back to outline + defaultValue capitalized label
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit -p frontend/tsconfig.app.json 2>&1 | grep -E "DatasetCard|error" | head -20</automated>
  </verify>
  <done>TypeScript compiles without errors. The badge renders from t() and applies amber/secondary/outline variants per status.</done>
</task>

</tasks>

<verification>
After both tasks:
1. `npx tsc --noEmit -p frontend/tsconfig.app.json` passes with no errors in DatasetCard.tsx
2. Grep confirms no hardcoded 'Draft' string remains: `grep -n "'Draft'" frontend/src/components/search/DatasetCard.tsx` returns nothing
3. All four locale files contain `card.status.draft`
</verification>

<success_criteria>
- record_status badge label is always from t('card.status.*') with capitalized fallback
- draft → amber outline badge (unchanged visual)
- archived → secondary (neutral filled) badge
- deprecated → outline badge with muted text
- No hardcoded English status strings in DatasetCard.tsx
- TypeScript compiles clean
</success_criteria>

<output>
After completion, create `.planning/quick/50-i18n-and-distinct-badge-variants-for-rec/50-SUMMARY.md`
</output>
