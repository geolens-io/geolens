import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist', 'coverage']),
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
    rules: {
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/refs': 'off',
      'react-hooks/preserve-manual-memoization': 'off',
      'react-refresh/only-export-components': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // SEC-S14 (sec-audit-20260519.md): ban writing token/jwt/auth values to localStorage.
      // Any future code that reaches for localStorage.setItem('myjwt', ...) or similar will
      // fail lint, preventing inadvertent regression of the token-storage surface.
      // The single legitimate write site (zustand persist for geolens-auth) does NOT call
      // localStorage.setItem directly — zustand middleware wraps it inside node_modules.
      // Known limitation: identifier and template-literal first args slip through the AST
      // selector (requires 'Literal' type). This catches accidental/cargo-cult regression,
      // not motivated evasion. See docs-internal/audits/security-lessons.md for rationale
      // and the medium-term httpOnly-cookie migration plan.
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
    // SEC-S14 exemption: auth-store test legitimately writes the 'geolens-auth' persist key
    // to set up zustand fixtures. The rule's intent is to catch NEW token writes in
    // application code, not test setup of the existing single legitimate write site.
    files: ['src/stores/__tests__/auth-store.test.ts'],
    rules: { 'no-restricted-syntax': 'off' },
  },
])
