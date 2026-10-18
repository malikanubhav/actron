'use client'
import { useEffect, useRef } from 'react'
import { BrandMark } from '@/components/brand/BrandMark'

/** The main action; focused on load (PROMPT 8.8 A). A plain link: the server redirects to Slack. */
export function SlackSignIn({ next }: { next: string }) {
  const ref = useRef<HTMLAnchorElement>(null)
  useEffect(() => {
    // Focused so Enter signs in, without drawing the focus ring before the person has used the keyboard.
    ref.current?.focus({ focusVisible: false } as FocusOptions)
  }, [])
  return (
    <a
      ref={ref}
      href={`/api/auth/slack/start?next=${encodeURIComponent(next)}`}
      className="press inline-flex h-11 items-center gap-3 rounded-md bg-accent px-5 text-body font-medium text-accent-ink hover:bg-accent/90"
      data-testid="slack-signin"
    >
      <span className="inline-flex size-6 items-center justify-center rounded-sm bg-ink-0">
        <BrandMark name="slack" size={16} decorative />
      </span>
      Sign in with Slack
    </a>
  )
}
