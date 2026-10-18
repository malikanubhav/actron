import { expect, test } from '@playwright/test'

test('C-AC-41 the landing Open Graph image renders as a PNG', async ({ request, page }) => {
  await page.goto('/')
  const og = await page.locator('meta[property="og:image"]').first().getAttribute('content')
  expect(og).toMatch(/opengraph-image/)
  const res = await request.get(new URL(og as string).pathname + (new URL(og as string).search ?? ''))
  expect(res.status()).toBe(200)
  expect(res.headers()['content-type']).toContain('image/png')
  expect((await res.body()).byteLength).toBeGreaterThan(10_000)
})

test('C-AC-41 brand assets exist: logo, wordmark, favicons, touch icon, manifest', async ({ request }) => {
  for (const path of [
    '/actron-brand/logo.svg',
    '/actron-brand/wordmark.svg',
    '/actron-brand/favicon.svg',
    '/actron-brand/favicon-32.png',
    '/actron-brand/favicon-16.png',
    '/actron-brand/apple-touch-icon.png',
    '/actron-brand/icon-192.png',
    '/actron-brand/icon-512.png',
    '/manifest.webmanifest',
  ]) {
    const res = await request.get(path)
    expect(res.status(), path).toBe(200)
  }
})
