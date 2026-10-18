import { defineConfig, globalIgnores } from 'eslint/config'
import nextVitals from 'eslint-config-next/core-web-vitals'
import nextTs from 'eslint-config-next/typescript'

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'no-console': ['error', { allow: ['warn', 'error'] }],
      'react/no-unescaped-entities': 'off',
    },
  },
  {
    files: ['tests/**', 'scripts/**', 'playwright.config.ts', 'vitest.config.ts', 'vitest.setup.ts'],
    rules: {
      'no-console': 'off',
      '@next/next/no-img-element': 'off',
    },
  },
  globalIgnores([
    '.next/**',
    '.next-fixtures/**',
    '.next-e2e/**',
    'out/**',
    'build/**',
    'next-env.d.ts',
    'public/mockServiceWorker.js',
    'lib/api/openapi.d.ts',
    'coverage/**',
    'test-results/**',
    'playwright-report/**',
    '.lighthouseci/**',
  ]),
])

export default eslintConfig
