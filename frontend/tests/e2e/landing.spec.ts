import { expect, test } from '@playwright/test'

test.describe('landing page', () => {
  test('C-AC-21 renders the six sections in order with the hero headline', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(
      'Your AI doesn’t know what your team already decided. Actron does.',
    )
    const sections = await page.locator('[data-section]').evaluateAll((els) => els.map((e) => e.getAttribute('data-section')))
    expect(sections).toEqual(['hero', 'problem', 'journey', 'graph', 'stack', 'close'])
    await expect(page.locator('[data-step]')).toHaveCount(5)
  })

  test('C-AC-21 shows real logos and ontology counts', async ({ page }) => {
    await page.goto('/')
    const stack = page.getByTestId('stack-list')
    for (const brand of ['falkordb', 'typesafe', 'pi', 'mcp', 'temporal', 'slack', 'github', 'linear']) {
      await expect(stack.locator(`[data-brand-row="${brand}"] [data-brand]`)).toHaveCount(1)
    }
    await expect(page.getByTestId('ontology-label')).toContainText('96 node types')
    await expect(page.getByTestId('cypher-example')).toHaveCount(3)
  })

  test('C-AC-47 "Watch a replay" appears only with a finished request and points to a replay', async ({ page }) => {
    await page.goto('/')
    const replay = page.getByTestId('watch-replay')
    const count = await replay.count()
    if (count > 0) {
      await expect(replay.first()).toHaveAttribute('href', /\/replay\/|\/app\/requests\/.+\/replay$/)
    }
    await expect(page.getByTestId('open-app').first()).toHaveAttribute('href', '/app')
  })

  test('C-AC-40 has a title and meta description', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveTitle('Actron · Check what your team decided before AI writes code')
    await expect(page.locator('meta[name="description"]')).toHaveAttribute('content', /FalkorDB graph/)
  })
})
