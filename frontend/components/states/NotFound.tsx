import Link from 'next/link'
import { ActronMark } from '../brand/ActronLogo'
import { buttonClass } from '../ui/button-class'

/** 404 in the product's voice (PRD 13.9b; C-AC-40). */
export function NotFoundContent({ home = '/app' }: { home?: string }) {
  return (
    <div className="flex max-w-2xl flex-col items-start gap-5 py-24" data-testid="not-found">
      <ActronMark size={36} className="text-fg-3" />
      <p className="eyebrow">Not found · 404</p>
      <h1 className="display text-headline-sm text-fg-1">This page isn’t in Actron’s memory.</h1>
      <p className="text-lead text-fg-2">The link may be old, or the page belongs to another workspace. Press Ctrl K (⌘K on a Mac) to search, or go back to your requests.</p>
      <div className="flex gap-2">
        <Link href={home} className={buttonClass('primary')}>
          Back to requests
        </Link>
        <Link href="/" className={buttonClass('secondary')}>
          About Actron
        </Link>
      </div>
    </div>
  )
}

/** 500 in the product's voice. */
export function ServerErrorContent({ digest, onRetry }: { digest?: string; onRetry?: () => void }) {
  return (
    <div className="flex max-w-2xl flex-col items-start gap-5 py-24" role="alert" data-testid="server-error">
      <ActronMark size={36} className="text-fg-3" />
      <p className="eyebrow">Something broke · 500</p>
      <h1 className="display text-headline-sm text-fg-1">Actron hit an error showing this page.</h1>
      <p className="text-lead text-fg-2">
        Your requests and builds are safe; they run on the server. Try again, and if it keeps happening, share the reference below with whoever runs Actron.
      </p>
      {digest ? (
        <p className="text-caption text-fg-3">
          Reference <span className="data-label text-fg-2">{digest}</span>
        </p>
      ) : null}
      <div className="flex gap-2">
        {onRetry ? (
          <button type="button" onClick={onRetry} className={buttonClass('primary')}>
            Try again
          </button>
        ) : null}
        <Link href="/app" className={buttonClass('secondary')}>
          Back to requests
        </Link>
      </div>
    </div>
  )
}
