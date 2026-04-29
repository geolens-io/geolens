# /i18n-check — Internationalization Readiness Audit

Audit GeoLens for internationalization (i18n) readiness: hardcoded strings, locale-dependent formatting, translation infrastructure, RTL layout support, and standards-level language metadata. GeoLens targets government and enterprise buyers — many procurement processes require i18n readiness documentation even for English-only initial deployments. This command assesses how much work a full localization would take, without requiring one today.

**Usage:** `/i18n-check` (full audit) or `/i18n-check <area>` where area is `strings`, `formatting`, `infra`, `rtl`, `standards`, or `a11y`

---

## INTAKE (Serial — do this first)

### Step 1: Detect existing i18n infrastructure

```bash
# i18n libraries
grep -rn "i18n\|i18next\|react-intl\|react-i18next\|formatjs\|lingui\|polyglot\|rosetta\|next-intl\|typesafe-i18n" frontend/package.json frontend/src/ --include="*.ts" --include="*.tsx" --include="*.json" 2>/dev/null | grep -v node_modules | head -20

# Locale/translation files
find frontend/src -name "*.json" -path "*locale*" -o -name "*.json" -path "*lang*" -o -name "*.json" -path "*i18n*" -o -name "*.json" -path "*translation*" -o -name "*.json" -path "*messages*" 2>/dev/null | grep -v node_modules

find frontend/ -type d -name "locales" -o -name "lang" -o -name "i18n" -o -name "translations" -o -name "messages" 2>/dev/null | grep -v node_modules

# Backend i18n
grep -rn "gettext\|babel\|i18n\|locale\|Locale\|Accept-Language" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__

# Language/locale settings
grep -rn "LANGUAGE\|LOCALE\|DEFAULT_LANG\|lang\|language" .env.example backend/app/modules/settings/ --include="*.py" --include="*.env*" 2>/dev/null | grep -v __pycache__
```

### Step 2: Inventory the UI surface

```bash
# Count total components and pages
COMPONENTS=$(find frontend/src/components -name "*.tsx" 2>/dev/null | grep -v node_modules | wc -l)
PAGES=$(find frontend/src/pages -name "*.tsx" 2>/dev/null | grep -v node_modules | wc -l)
echo "Components: $COMPONENTS | Pages: $PAGES"

# Get the full file list for string scanning
find frontend/src -name "*.tsx" -o -name "*.ts" 2>/dev/null | grep -v node_modules | sort > /tmp/frontend-files.txt
wc -l /tmp/frontend-files.txt
```

### Step 3: Read formatting and locale patterns

```bash
# Date formatting
grep -rn "toLocaleDateString\|toLocaleString\|toLocaleTimeString\|Intl\.DateTimeFormat\|date-fns\|dayjs\|moment\|format.*date\|formatDate\|new Date.*toISO\|\.toISOString" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | head -30

# Number formatting
grep -rn "toLocaleString\|toFixed\|Intl\.NumberFormat\|formatNumber\|\.toLocaleString\|number.*format\|currency\|percent" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | head -20

# Sorting and collation
grep -rn "\.sort\|localeCompare\|Intl\.Collator" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | head -15

# Backend date/number formatting
grep -rn "strftime\|isoformat\|datetime.*format\|locale\|number_format\|f\"{.*:,\}\|f\"{.*:.2f" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__ | head -20
```

---

## SUBAGENT DISPATCH (Parallel)

Run these 6 subagents in parallel.

### Subagent 1: Hardcoded String Inventory

**Goal:** Find every user-visible English string hardcoded in the frontend. This is the largest i18n debt category and determines the scope of any future translation effort.

**Process:**

#### 1a. JSX text content

```bash
# Strings in JSX — text between tags
# This catches: <p>Hello world</p>, <Button>Save</Button>, <h1>Dashboard</h1>
find frontend/src -name "*.tsx" 2>/dev/null | grep -v node_modules | while read f; do
  # Count lines with English text in JSX (rough heuristic: lines with >tag< content >text<)
  HITS=$(grep -n ">[A-Z][a-z]" "$f" 2>/dev/null | grep -v "import\|from\|//\|{/\*" | wc -l)
  if [ "$HITS" -gt 0 ]; then
    echo "$f: ~$HITS hardcoded strings"
  fi
done | sort -t: -k2 -rn | head -30
```

#### 1b. String literals in component props

```bash
# Strings passed as props: title="...", label="...", description="...", placeholder="..."
grep -rn "title=\"[A-Z]\|label=\"[A-Z]\|description=\"[A-Z]\|placeholder=\"[A-Z]\|alt=\"[A-Z]\|aria-label=\"[A-Z]\|message=\"[A-Z]\|heading=\"[A-Z]\|tooltip=\"[A-Z]" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules | head -40

# Template literals with English text
grep -rn '`[A-Z][^`]*`\|`[^`]*[a-z] [a-z][^`]*`' frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep -v "import\|from\|url\|path\|http\|api/" | head -30
```

#### 1c. Error messages and notifications

```bash
# Toast / notification messages
grep -rn "toast\|Toast\|notify\|Notification\|alert\|Alert\|showError\|showSuccess\|addToast" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep -v "import\|from" | head -20

# Error message strings
grep -rn "Error\|error\|failed\|Failed\|success\|Success\|warning\|Warning" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep -v "import\|from\|interface\|type \|\.error\b\|console\." | grep "['\"]" | head -30

# Backend error messages returned to the frontend
grep -rn "detail=\|message=\|HTTPException.*detail\|raise.*detail" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__ | grep "['\"]" | head -30
```

#### 1d. Navigation and menu labels

```bash
# Nav items, menu labels, breadcrumbs
grep -rn "label:\|title:\|to:\|name:" frontend/src/components/layout/ frontend/src/components/admin/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep "['\"][A-Z]" | head -20

# Sidebar and navbar labels
find frontend/src -name "*Navbar*" -o -name "*Sidebar*" -o -name "*Nav*" -o -name "*Menu*" 2>/dev/null | grep -E "\.(tsx|ts)$" | grep -v node_modules | while read f; do
  STRINGS=$(grep -c "['\"][A-Z][a-z]" "$f" 2>/dev/null)
  echo "$f: ~$STRINGS strings"
done
```

#### 1e. Form labels and validation messages

```bash
# Form labels
grep -rn "<Label\|htmlFor\|<label" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules | grep "['\"][A-Z]" | head -20

# Validation messages
grep -rn "required\|invalid\|must be\|cannot be\|too short\|too long\|minimum\|maximum\|pattern\|format" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep "['\"]" | head -20

# Zod / yup / form validation schemas
grep -rn "\.message(\|\.min(\|\.max(\|\.required(\|\.email(\|\.url(" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep "['\"]" | head -20
```

#### 1f. String concatenation anti-patterns

```bash
# String concatenation that breaks translation (word order differs across languages)
# Pattern: "string" + variable + "string" or `string ${var} string`
grep -rn '+ "[a-z]\|+ '"'"'[a-z]\|`[A-Z][^`]*\${' frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep -v "import\|from\|url\|path\|api\|http\|console" | head -20
```

String concatenation is the most dangerous i18n anti-pattern. "Showing {count} results" works in English but the word order changes in German ("Zeigt {count} Ergebnisse an"), Japanese ("{count}件の結果を表示"), and Arabic (RTL + different order). These must be full interpolated strings in any i18n system.

#### 1g. Generate string inventory summary

Produce a count by category:

| Category | Estimated count | Example |
|----------|----------------|---------|
| JSX text content | ? | `<h1>Dashboard</h1>` |
| Component props | ? | `title="Search datasets"` |
| Error/notification messages | ? | `toast.error("Upload failed")` |
| Navigation labels | ? | `{ label: "Collections", to: "/collections" }` |
| Form labels/validation | ? | `<Label>Dataset name</Label>` |
| Backend error messages | ? | `detail="Dataset not found"` |
| **Total** | **?** | |

**Output:** String inventory by category with counts, top 20 files by string density, and string concatenation anti-patterns.

---

### Subagent 2: Date, Number & Locale Formatting

**Goal:** Find every instance of locale-dependent formatting and assess whether it would produce correct output for non-English locales.

**Process:**

#### 2a. Date formatting audit

```bash
# Read all date formatting code
grep -rn "toLocaleDateString\|toLocaleString\|toLocaleTimeString\|Intl\.DateTimeFormat\|format(" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | head -30

# date-fns or dayjs usage (locale-aware?)
grep -rn "date-fns\|dayjs\|format\|formatDistance\|formatRelative\|fromNow" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep -v "import.*from" | head -20

# Hardcoded date formats (month names, ordinals)
grep -rn "January\|February\|March\|April\|May\|June\|July\|August\|September\|October\|November\|December\|Jan\|Feb\|Mar\|Apr\|Jun\|Jul\|Aug\|Sep\|Oct\|Nov\|Dec" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | head -10

# Manual date string construction
grep -rn "getMonth\|getDate\|getFullYear\|getHours\|getMinutes" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | head -10

# ISO 8601 dates (locale-safe)
grep -rn "toISOString\|ISO\|isoformat" frontend/src/ backend/app/ --include="*.tsx" --include="*.ts" --include="*.py" 2>/dev/null | grep -v node_modules | grep -v __pycache__ | head -15
```

**Date formatting rules:**
- `Intl.DateTimeFormat` or `toLocaleDateString` with explicit locale parameter → ✅ locale-safe
- `toLocaleDateString()` without locale → ⚠️ uses browser default (works but inconsistent)
- `format(date, 'MM/dd/yyyy')` (date-fns without locale) → ❌ US format hardcoded
- Manual `getMonth()` + month name array → ❌ hardcoded English
- ISO 8601 strings → ✅ locale-neutral (but need formatting for display)

#### 2b. Number formatting audit

```bash
# Number display
grep -rn "toLocaleString\|Intl\.NumberFormat\|toFixed\|\.toLocaleString(" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | head -20

# Hardcoded decimal separators or thousand separators
grep -rn '\.toFixed(\|"\."\|","\|number.*format' frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep -v "import\|from" | head -15

# File size formatting
grep -rn "bytes\|KB\|MB\|GB\|filesize\|file.*size\|humanize.*size\|format.*size\|pretty.*size" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | head -10

# Coordinate display (lat/lon) — these should NOT be localized (always use '.' as decimal)
grep -rn "latitude\|longitude\|lat\|lng\|lon\|coordinate\|latlng\|LatLng" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep -i "display\|format\|toFixed\|toString" | head -15
```

**Number formatting rules:**
- `Intl.NumberFormat` with locale → ✅ locale-safe
- `.toLocaleString()` without locale → ⚠️ uses browser default
- `.toFixed(2)` for display → ❌ always uses '.' as decimal separator (1234.56 vs 1234,56 in European locales)
- **Exception:** Geographic coordinates MUST always use '.' decimal separator regardless of locale (ISO 6709). Do NOT flag coordinate formatting as a i18n issue.

#### 2c. Relative time formatting

```bash
# "2 hours ago", "just now", "yesterday" patterns
grep -rn "ago\|just now\|yesterday\|today\|tomorrow\|time.*since\|relative.*time\|formatDistance\|formatRelative\|fromNow\|timeago\|Intl\.RelativeTimeFormat" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | head -15
```

Relative time strings ("3 days ago") are some of the hardest to internationalize because of pluralization rules. Flag any hand-rolled relative time formatting.

#### 2d. Currency and units

```bash
# Currency
grep -rn "currency\|USD\|\\\$\|€\|£\|¥\|Intl\.NumberFormat.*currency" frontend/src/ backend/app/ --include="*.tsx" --include="*.ts" --include="*.py" 2>/dev/null | grep -v node_modules | grep -v __pycache__ | head -10

# Measurement units (may appear in spatial contexts)
grep -rn "meters\|kilometres\|kilometers\|miles\|feet\|acres\|hectares\|sq km\|sq mi\|m²\|km²" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | head -10
```

Units of measurement in a geospatial app are locale-sensitive — US buyers expect miles/feet, European buyers expect km/meters. Flag hardcoded unit strings and check if there's a unit preference system.

#### 2e. Sorting and collation

```bash
# Sort operations on user-visible text
grep -rn "\.sort(\|localeCompare\|Intl\.Collator" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | head -15
```

- `.sort()` with no comparator → ❌ uses Unicode code point order (fails for accented characters)
- `.sort((a, b) => a.localeCompare(b))` → ⚠️ uses browser default locale
- `.sort((a, b) => a.localeCompare(b, locale))` → ✅ locale-aware
- `Intl.Collator` → ✅ locale-aware

**Output:** Formatting inventory — Category | Count | Locale-safe | Hardcoded | Fix needed

---

### Subagent 3: Translation Infrastructure Assessment

**Goal:** Assess whether i18n plumbing exists, and if not, estimate the effort to add it.

**Process:**

#### 3a. Current infrastructure

```bash
# i18n library presence
cat frontend/package.json 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
deps = {**d.get('dependencies', {}), **d.get('devDependencies', {})}
i18n_libs = [k for k in deps if any(term in k.lower() for term in ['i18n', 'intl', 'lingui', 'formatjs', 'polyglot', 'rosetta'])]
print('i18n libraries:', i18n_libs if i18n_libs else 'NONE')
" 2>/dev/null

# Provider/context for locale
grep -rn "I18nProvider\|IntlProvider\|LocaleProvider\|LanguageProvider\|i18n.*init\|i18n.*use" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules

# Language switcher UI
grep -rn "language\|Language\|locale\|Locale\|lang.*select\|lang.*switch\|lang.*toggle" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules | grep -iv "import\|program.*lang\|html.*lang"

# Locale detection
grep -rn "navigator\.language\|Accept-Language\|locale.*detect\|browser.*lang" frontend/src/ backend/app/ --include="*.tsx" --include="*.ts" --include="*.py" 2>/dev/null | grep -v node_modules | grep -v __pycache__

# HTML lang attribute
grep -rn "lang=" frontend/index.html frontend/src/ --include="*.html" --include="*.tsx" 2>/dev/null | grep -v node_modules | head -5
```

#### 3b. Translation file structure

```bash
# Existing translation/locale files
find frontend/ -name "*.json" -path "*locale*" -o -name "*.json" -path "*lang*" -o -name "*.json" -path "*i18n*" -o -name "*.json" -path "*translation*" 2>/dev/null | grep -v node_modules

# If translation files exist, read structure
find frontend/ \( -path "*locale*" -o -path "*i18n*" -o -path "*translation*" \) -name "*.json" 2>/dev/null | grep -v node_modules | while read f; do
  echo "=== $f ==="
  head -30 "$f"
done
```

#### 3c. Infrastructure readiness assessment

Based on findings, classify the current state:

| Level | Description |
|-------|-------------|
| **Level 0: No infrastructure** | No i18n library, no translation files, no locale detection. All strings hardcoded. |
| **Level 1: Partial awareness** | Some `Intl` API usage for dates/numbers, but no string externalization. |
| **Level 2: Infrastructure exists** | i18n library installed, some strings externalized, but incomplete coverage. |
| **Level 3: Translation-ready** | All user-visible strings externalized, locale switching works, at least English locale file complete. |
| **Level 4: Translated** | Multiple locale files with actual translations. |

#### 3d. Recommended i18n architecture

If Level 0 or 1, provide a concrete recommendation:

**Recommended library:** `react-i18next` (most popular, good TypeScript support, lazy loading, namespace support)

**Recommended file structure:**
```
frontend/src/
  i18n/
    config.ts              # i18n initialization
    locales/
      en/
        common.json        # Shared strings (nav, buttons, errors)
        search.json        # Search page strings
        maps.json          # Map builder strings
        admin.json         # Admin panel strings
        ai.json            # AI feature strings
        standards.json     # OGC/STAC/DCAT strings
      [future_locale]/
        common.json
        ...
```

**Namespacing by GeoLens domain** matches the existing code organization and prevents a single massive translation file.

**Effort estimate:**
- Install and configure react-i18next: 2–4 hours
- Extract strings from the 10 most critical pages: 2–3 days
- Extract all remaining strings: 1–2 weeks
- Actual translation per language: External cost (varies by language and word count)

**Output:** Infrastructure level assessment, recommended architecture, effort estimate.

---

### Subagent 4: RTL Layout Readiness

**Goal:** Assess whether the UI could support right-to-left languages (Arabic, Hebrew, Farsi) without major layout breakage. Full RTL support isn't required for launch, but knowing the debt level is valuable for procurement documentation.

**Process:**

#### 4a. Directional CSS audit

```bash
# Hardcoded left/right in CSS (should use logical properties for RTL)
grep -rn "margin-left\|margin-right\|padding-left\|padding-right\|text-align:\s*left\|text-align:\s*right\|float:\s*left\|float:\s*right\|left:\|right:" frontend/src/ --include="*.css" --include="*.scss" 2>/dev/null | grep -v node_modules | head -20

# Tailwind directional classes (physical vs logical)
# Physical (break in RTL): ml-, mr-, pl-, pr-, left-, right-, text-left, text-right
# Logical (RTL-safe): ms-, me-, ps-, pe-, start-, end-, text-start, text-end
grep -rn "\bml-\|\bmr-\|\bpl-\|\bpr-\|\bleft-\|\bright-\|\btext-left\|\btext-right" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | wc -l

grep -rn "\bms-\|\bme-\|\bps-\|\bpe-\|\bstart-\|\bend-\|\btext-start\|\btext-end" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | wc -l

echo "Physical (RTL-breaking) vs Logical (RTL-safe) directional class ratio"
```

#### 4b. Flexbox and grid direction

```bash
# flex-row is LTR by default — flex-row-reverse would be needed for RTL in some cases
# Most flexbox layouts auto-flip in RTL if using logical properties
grep -rn "flex-row\|flex-row-reverse\|flex-direction" frontend/src/ --include="*.tsx" --include="*.ts" --include="*.css" 2>/dev/null | grep -v node_modules | wc -l

# Absolute positioning that might break in RTL
grep -rn "absolute.*left\|absolute.*right\|fixed.*left\|fixed.*right" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules | head -15
```

#### 4c. Icon directionality

```bash
# Directional icons (arrows, chevrons) that should mirror in RTL
grep -rn "ArrowLeft\|ArrowRight\|ChevronLeft\|ChevronRight\|ArrowBack\|ArrowForward" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules | head -15
```

Directional icons (← →) must mirror in RTL. Non-directional icons (✓ ✕ ⚙) must not.

#### 4d. Map-specific RTL concerns

```bash
# Map controls positioning
grep -rn "top-left\|top-right\|bottom-left\|bottom-right\|NavigationControl\|position.*control" frontend/src/components/map/ frontend/src/components/builder/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules

# Drawing toolbar position (centered — RTL-safe)
grep -rn "left-1/2\|translate-x\|translate-y" frontend/src/components/drawing/ --include="*.tsx" 2>/dev/null | grep -v node_modules
```

MapLibre GL controls have their own positioning system that doesn't respect CSS `direction: rtl`. Map control placement would need explicit mirroring.

#### 4e. RTL readiness score

Calculate: `logical_classes / (logical_classes + physical_classes) × 100`

| Score | Assessment |
|-------|------------|
| > 80% | RTL-ready with minor fixes |
| 50–80% | Moderate effort — systematic find-replace for directional classes |
| < 50% | Significant effort — layout assumptions are heavily LTR |

**Output:** Physical vs logical class counts, specific RTL-breaking patterns, map control concerns, RTL readiness score.

---

### Subagent 5: Standards & Metadata Language Support

**Goal:** Verify that OGC/STAC/DCAT metadata endpoints support the `language` field and can serve multilingual metadata. This is a FAIR compliance requirement and a gov procurement checkbox.

**Process:**

#### 5a. DCAT language support

```bash
# DCAT language field
grep -rn "language\|dct:language\|dc:language\|@language\|xml:lang" backend/app/standards/dcat/ --include="*.py" 2>/dev/null | grep -v __pycache__

# DCAT catalog language declaration
grep -rn "catalog.*lang\|dataset.*lang\|distribution.*lang" backend/app/standards/dcat/ --include="*.py" 2>/dev/null | grep -v __pycache__
```

DCAT 2.0 requires:
- `dct:language` on Catalog (recommended)
- `dct:language` on Dataset (recommended)
- Values should be ISO 639-1 codes or URI references (e.g., `http://id.loc.gov/vocabulary/iso639-1/en`)

#### 5b. OGC Records language support

```bash
# OGC Records language field
grep -rn "language\|lang\|locale" backend/app/standards/ogc/ --include="*.py" 2>/dev/null | grep -v __pycache__
```

OGC API Records specifies:
- `properties.language` on each record (required in the core schema)
- Should support content negotiation by language (`Accept-Language` header)
- Multilingual title/description as language-tagged objects

#### 5c. STAC language support

```bash
# STAC doesn't mandate language, but common extensions include it
grep -rn "language\|lang" backend/app/standards/stac/ --include="*.py" 2>/dev/null | grep -v __pycache__
```

STAC doesn't require language fields in core, but the `language` extension exists. Note whether it's used.

#### 5d. Dataset metadata language field

```bash
# Does the dataset model have a language field?
grep -rn "language\|lang\|locale" backend/app/modules/catalog/datasets/models.py backend/app/modules/catalog/datasets/schemas.py 2>/dev/null | grep -v __pycache__

# Can metadata be stored in multiple languages?
grep -rn "translations\|multilingual\|multi_lang\|i18n\|localized" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__
```

#### 5e. Content negotiation by language

```bash
# Accept-Language header handling
grep -rn "Accept-Language\|accept.language\|content.language\|Content-Language" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__
```

For standards endpoints serving metadata, `Accept-Language` content negotiation enables clients to request metadata in their preferred language. This is a DCAT-AP requirement and an OGC Records recommendation.

#### 5f. AI metadata language awareness

```bash
# Does AI metadata generation consider language?
grep -rn "language\|lang\|english\|locale" backend/app/processing/ai/ --include="*.py" 2>/dev/null | grep -v __pycache__
```

If the AI generates metadata (descriptions, keywords) in English only, note this — future multilingual support would need language-aware prompt routing.

**Output:** Standards language compliance matrix — Standard | Field | Present | Correct format | Content negotiation

---

### Subagent 6: Text Handling & Unicode Safety

**Goal:** Verify the application handles Unicode correctly — non-Latin scripts, emoji, bidirectional text, combining characters. Even English-only deployments receive user-generated content (dataset names, descriptions, search queries) that may contain Unicode.

**Process:**

#### 6a. Database text encoding

```bash
# PostgreSQL encoding
docker compose exec -T db psql -U postgres -c "SHOW server_encoding;" 2>/dev/null
docker compose exec -T db psql -U postgres -c "SHOW client_encoding;" 2>/dev/null
docker compose exec -T db psql -U postgres -d geolens -c "
  SELECT datname, encoding, datcollate, datctype
  FROM pg_database
  WHERE datname = 'geolens';
" 2>/dev/null
```

PostgreSQL should use `UTF8` encoding. Collation (`datcollate`) affects sorting — `en_US.UTF-8` sorts differently than `C` or locale-specific collations.

#### 6b. Text length validation

```bash
# String length checks — do they count bytes or characters?
grep -rn "\.length\|maxLength\|max_length\|MaxLen\|minLength\|min_length\|CharField.*max\|String(" frontend/src/ backend/app/ --include="*.tsx" --include="*.ts" --include="*.py" 2>/dev/null | grep -v node_modules | grep -v __pycache__ | head -20
```

JavaScript `.length` counts UTF-16 code units, not characters. Emoji and CJK characters can cause surprising length mismatches between frontend validation and database constraints:
- `"Hello".length` → 5
- `"こんにちは".length` → 5
- `"👨‍👩‍👧‍👦".length` → 11 (family emoji is multiple code points)

#### 6c. Text truncation safety

```bash
# String truncation/slicing
grep -rn "\.substring\|\.slice\|\.substr\|truncat\|ellipsis\|overflow.*hidden.*text\|text-ellipsis\|line-clamp" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | head -20
```

Naive `string.slice(0, 100)` can split a multi-byte character or an emoji in half, producing invalid UTF-8. Use `Intl.Segmenter` or a grapheme-aware library for safe truncation.

#### 6d. Search and text processing

```bash
# Text normalization for search
grep -rn "normalize\|NFC\|NFD\|NFKC\|NFKD\|toLowerCase\|toUpperCase\|toLocaleLowerCase\|unaccent\|diacrit" backend/app/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx" 2>/dev/null | grep -v node_modules | grep -v __pycache__ | head -20

# PostgreSQL unaccent extension (for accent-insensitive search)
docker compose exec -T db psql -U postgres -c "SELECT * FROM pg_extension WHERE extname = 'unaccent';" 2>/dev/null
```

For search across languages:
- `unaccent` PostgreSQL extension enables accent-insensitive search (café = cafe)
- Unicode normalization (NFC) should be applied before comparison
- `pg_trgm` works with Unicode but trigram quality varies by script
- Full-text search (`tsvector`) requires language-specific dictionaries

#### 6e. Font and rendering

```bash
# Font configuration — does Inter Variable support required Unicode ranges?
grep -rn "fontsource\|Inter\|unicode-range\|font-family" frontend/src/ --include="*.css" --include="*.ts" --include="*.tsx" 2>/dev/null | grep -v node_modules | head -10
```

Inter Variable has excellent Latin, Cyrillic, and Greek coverage but limited CJK (Chinese/Japanese/Korean) and Arabic support. For a geospatial platform receiving international data, the font stack fallback matters:
- Inter Variable → system-ui → sans-serif covers most cases
- CJK-heavy deployments would need a CJK font in the stack

#### 6f. URL and file path encoding

```bash
# Non-ASCII in URLs (dataset names, search queries become URL params)
grep -rn "encodeURIComponent\|encodeURI\|decodeURIComponent\|urllib\.parse\|quote\|unquote" frontend/src/ backend/app/ --include="*.tsx" --include="*.ts" --include="*.py" 2>/dev/null | grep -v node_modules | grep -v __pycache__ | head -15

# File upload name handling (non-Latin filenames)
grep -rn "filename\|file\.name\|original.*name\|upload.*name" backend/app/processing/ingest/ --include="*.py" 2>/dev/null | grep -v __pycache__
```

Dataset names and search queries containing non-ASCII characters must be properly URL-encoded. File uploads with non-Latin filenames (common in international datasets) must be handled safely.

**Output:** Unicode safety assessment — Area | Status | Risk | Remediation

---

## SYNTHESIS (Serial — after all subagents complete)

### i18n Readiness Scorecard

| Dimension | What it measures | Grade |
|-----------|-----------------|-------|
| **String Externalization** | What percentage of user-visible strings are externalized? | A–F |
| **Formatting** | Are dates, numbers, and units locale-aware? | A–F |
| **Infrastructure** | Is i18n plumbing in place (library, locale files, provider)? | A–F |
| **RTL Layout** | Could the layout support RTL languages? | A–F |
| **Standards Metadata** | Do OGC/STAC/DCAT endpoints support language fields? | A–F |
| **Unicode Safety** | Does the app handle non-Latin text correctly? | A–F |

**Overall i18n readiness level:** Level 0–4 (from Subagent 3 assessment)

### Translation Effort Estimate

| Scope | Strings (est.) | Effort to externalize | Effort to translate (per language) |
|-------|----------------|----------------------|-----------------------------------|
| Critical path (nav, errors, forms) | ? | ? hours | ? words |
| Full UI | ? | ? days | ? words |
| Backend error messages | ? | ? hours | ? words |
| Standards metadata | ? | ? hours | N/A (data-dependent) |
| **Total** | **?** | **?** | **?** |

### Procurement Compliance Assessment

For government procurement, assess these common i18n requirements:

| Requirement | Status | Notes |
|-------------|--------|-------|
| UTF-8 throughout (database, API, UI) | ✅/❌ | |
| Language metadata in standards endpoints | ✅/❌ | DCAT, OGC Records |
| HTML `lang` attribute set | ✅/❌ | Accessibility + i18n |
| Date/number formatting uses Intl API | ✅/❌ | |
| UI string externalization possible | ✅/❌ | Architecture allows it |
| RTL layout feasible without rewrite | ✅/❌ | |
| Non-Latin filenames handled safely | ✅/❌ | Upload pipeline |
| Search works with Unicode input | ✅/❌ | pg_trgm + tsvector |

### Action Items

| Field | Description |
|-------|-------------|
| Priority | P0 (Unicode bug — data corruption risk), P1 (procurement checkbox — blocks gov sales), P2 (i18n debt — matters when translation begins) |
| Action | Specific fix with file path |
| Category | Strings / Formatting / Infrastructure / RTL / Standards / Unicode |
| Effort | Hours estimate |
| Blocks | What capability this enables |

Sort by: priority → effort.

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/i18n-check-{YYYYMMDD}.md`

### Report structure

```markdown
# Internationalization Readiness Audit — {YYYY-MM-DD}

## Scorecard
<!-- Grades per dimension + overall i18n level -->

## Executive Summary
<!-- 3-5 sentences: current i18n state, procurement readiness, effort to full i18n -->

## 1. Hardcoded String Inventory
### 1a. JSX Text Content
### 1b. Component Props
### 1c. Error Messages & Notifications
### 1d. Navigation & Menu Labels
### 1e. Form Labels & Validation
### 1f. String Concatenation Anti-Patterns
### 1g. Inventory Summary

## 2. Date, Number & Locale Formatting
### 2a. Date Formatting
### 2b. Number Formatting
### 2c. Relative Time
### 2d. Units of Measurement
### 2e. Sorting & Collation

## 3. Translation Infrastructure
### 3a. Current State
### 3b. Translation File Structure
### 3c. Infrastructure Level Assessment
### 3d. Recommended Architecture

## 4. RTL Layout Readiness
### 4a. Directional CSS
### 4b. Flexbox & Grid
### 4c. Icon Directionality
### 4d. Map Controls
### 4e. RTL Readiness Score

## 5. Standards & Metadata Language Support
### 5a. DCAT
### 5b. OGC Records
### 5c. STAC
### 5d. Content Negotiation

## 6. Unicode Safety
### 6a. Database Encoding
### 6b. Text Length Validation
### 6c. Truncation Safety
### 6d. Search & Normalization
### 6e. Font Coverage
### 6f. URL & Filename Encoding

## 7. Procurement Compliance Assessment
<!-- Requirements checklist -->

## 8. Translation Effort Estimate
<!-- Scope, string counts, effort projections -->

## 9. Prioritized Action Items
<!-- Action items table -->

## 10. Comparison to Prior Audit
<!-- If a previous i18n-check exists, diff findings -->
```

### Post-delivery

1. If `lessons.md` exists, append reusable insights about i18n patterns for geospatial applications.
2. Print summary: i18n level (0–4) + estimated total strings + P0 Unicode issues + procurement checkbox pass rate.

---

## WHAT NOT TO FLAG

- **Geographic coordinate formatting** — Coordinates MUST use `.` decimal separator regardless of locale (ISO 6709). Do NOT flag `toFixed()` on lat/lon values.
- **Technical identifiers in English** — API paths, JSON keys, CSS class names, environment variable names should stay in English. Only flag user-visible text.
- **Code comments in English** — These don't need translation.
- **Log messages** — Server-side log messages should stay in English for debuggability.
- **CRS identifiers** — `EPSG:4326`, `CRS84` etc. are technical identifiers, not translatable strings.
- **SPDX license identifiers** — `Apache-2.0`, `MIT` etc. are not translatable.
- **Enum values and status codes** — Internal enum values (`PENDING`, `COMPLETE`, `FAILED`) should not be translated. Only their display labels should be.
- **Test files** — Test assertions with English strings don't need externalization.
- **Third-party component text** — Text rendered by imported UI libraries (Radix, MapLibre controls) is outside GeoLens's control. Note it but don't count as GeoLens i18n debt.
- **No CJK font** — Inter Variable + system-ui fallback covers most cases. Only flag if the app explicitly targets CJK markets.