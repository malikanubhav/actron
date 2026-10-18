'use client'
import './globals.css'

/** Last resort when the root layout itself fails; renders its own html and body. */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en-GB">
      <body className="bg-ink-0 font-ui text-fg-1">
        <main className="mx-auto flex min-h-dvh max-w-2xl flex-col justify-center gap-5 px-6" role="alert">
          <p className="eyebrow">Something broke · 500</p>
          <h1 className="text-title-lg">Actron could not load.</h1>
          <p className="text-body text-fg-2">Your requests and builds are safe on the server. Reload the page; if it keeps failing, share the reference with whoever runs Actron.</p>
          {error.digest ? (
            <p className="text-caption text-fg-3">
              Reference <span className="data-label text-fg-2">{error.digest}</span>
            </p>
          ) : null}
          <div>
            <button type="button" onClick={reset} className="h-9 rounded-md bg-accent px-4 text-small font-medium text-accent-ink">
              Reload
            </button>
          </div>
        </main>
      </body>
    </html>
  )
}
