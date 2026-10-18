import { expect, test } from '@playwright/test'
import { FIXTURE_IDS, fast, open } from './helpers'

test.use({ reducedMotion: 'reduce' })

/** C-AC-7: with reduced motion nothing animates position or rotation. */
async function movingAnimations(page: import('@playwright/test').Page) {
  return page.evaluate(() =>
    document
      .getAnimations()
      .filter((a) => a.playState === 'running')
      .map((a) => {
        const effect = a.effect as KeyframeEffect | null
        const frames = effect?.getKeyframes() ?? []
        const props = new Set(frames.flatMap((f) => Object.keys(f)))
        return { name: (a as CSSAnimation).animationName ?? 'js', props: [...props] }
      })
      .filter((a) => a.props.some((p) => ['transform', 'translate', 'rotate', 'scale', 'offsetDistance', 'left', 'top'].includes(p))),
  )
}

for (const path of ['/app', `/app/requests/${FIXTURE_IDS.live}`, '/app/system', '/app/dev/glyphs', '/']) {
  test(`C-AC-7 no moving animation on ${path}`, async ({ page }) => {
    await fast(page, 0.3)
    await open(page, path)
    await page.waitForTimeout(1500)
    expect(await movingAnimations(page)).toEqual([])
  })
}

test('C-AC-13 show path is immediate under reduced motion', async ({ page }) => {
  await open(page, `/app/requests/${FIXTURE_IDS.done}?tab=evidence`)
  await page.getByRole('button', { name: 'Show path' }).first().click()
  await expect(page.getByTestId('trace-quote').first()).toBeVisible({ timeout: 1500 })
})
