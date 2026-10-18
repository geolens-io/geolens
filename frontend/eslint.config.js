import js from '@eslint/js'
import globals from 'globals'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  // src/types/api.generated.ts is openapi-typescript output — 500KB of
  // generated declarations; linting it is wasteful and unfixable.
  globalIgnores(['dist', 'coverage', 'src/types/api.generated.ts']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
      jsxA11y.flatConfigs.recommended,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      react,
    },
    settings: {
      // Required by eslint-plugin-react to resolve the React version automatically.
      // Without this, the plugin emits a "React version not specified" warning.
      react: { version: 'detect' },
    },
    rules: {
      // Ban dangerouslySetInnerHTML in React components. The popup-template surface
      // (frontend/src/lib/popup-template.ts) bans this pattern in a comment; this
      // rule makes the ban machine-checkable.
      // Flip the regression fixture from .skip.tsx to .tsx and run `npm run lint` to
      // verify the rule fires.
      'react/no-danger': 'error',
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/refs': 'off',
      'react-hooks/preserve-manual-memoization': 'off',
      'react-refresh/only-export-components': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // Ban writing token/jwt/auth values to localStorage.
      // Code that reaches for localStorage.setItem('myjwt', ...) or similar fails
      // lint, which protects the token-storage surface.
      // The single legitimate write site (zustand persist for geolens-auth) does NOT call
      // localStorage.setItem directly — zustand middleware wraps it inside node_modules.
      // Known limitation: identifier and template-literal first args slip through the AST
      // selector (requires 'Literal' type). This catches accidental/cargo-cult regression,
      // not motivated evasion.
      // Browsers expose crypto.randomUUID only in secure contexts, so it throws
      // on a deployment served over plain HTTP; randomId() falls back.
      'no-restricted-properties': [
        'error',
        {
          object: 'crypto',
          property: 'randomUUID',
          message: 'crypto.randomUUID is missing on plain-HTTP origins; use randomId() from @/lib/random-id.',
        },
      ],
      'no-restricted-syntax': [
        'error',
        {
          selector:
            "CallExpression[callee.object.name='localStorage'][callee.property.name='setItem'][arguments.0.type='Literal'][arguments.0.value=/token|jwt|auth/i]",
          message:
            'SEC-S14 (sec-audit-20260519.md): writing token/jwt/auth values to localStorage is banned outside the central auth-store. Use useAuthStore.setAuth() or pick a non-token-shaped key. See docs-internal/audits/security-lessons.md for rationale + httpOnly migration plan.',
        },
      ],
    },
  },
  {
    // Exemption: auth-store test legitimately writes the 'geolens-auth' persist key
    // to set up zustand fixtures. The rule's intent is to catch NEW token writes in
    // application code, not test setup of the existing single legitimate write site.
    files: ['src/stores/__tests__/auth-store.test.ts'],
    rules: { 'no-restricted-syntax': 'off' },
  },
])
