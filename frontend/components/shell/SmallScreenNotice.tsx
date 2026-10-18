import { ActronMark } from '../brand/ActronLogo'

export const SMALL_SCREEN_TEXT = 'Actron works best on a larger screen. Approvals also work in Slack.'

/**
 * Below 1,024 px the app shows a calm message instead of a cramped layout (PRD 13.9b; C-AC-45). Pure CSS so it
 * works before hydration.
 */
export function SmallScreenNotice() {
  return (
    <div
      data-testid="small-screen-notice"
      className="fixed inset-0 z-[70] flex flex-col items-start justify-center gap-4 bg-ink-0 px-6 lg:hidden"
    >
      <ActronMark size={32} />
      <p className="eyebrow">Actron</p>
      <p className="display text-title text-fg-1">{SMALL_SCREEN_TEXT}</p>
      <p className="text-small text-fg-2">Open this page on a screen at least 1,024 pixels wide to see the timeline, the graph and the build.</p>
    </div>
  )
}
