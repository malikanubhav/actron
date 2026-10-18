import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import mdx from '@mdx-js/rollup'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [{ enforce: 'pre', ...mdx({ providerImportSource: undefined }) }, react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    include: ['tests/unit/**/*.test.{ts,tsx}'],
    css: false,
    restoreMocks: true,
    coverage: {
      provider: 'v8',
      include: ['components/**', 'lib/**'],
      reporter: ['text-summary', 'json-summary'],
    },
  },
})
