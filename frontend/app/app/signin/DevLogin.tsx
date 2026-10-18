'use client'
import { useState } from 'react'
import { endpoints } from '@/lib/api/endpoints'
import { newIdempotencyKey, reasonText } from '@/lib/api'
import { Button } from '@/components/ui/Button'

/** Development-only sign-in, marked with a DEV badge (PROMPT 8.8 A). */
export function DevLogin({ next }: { next: string }) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <div className="flex items-center gap-2">
      <Button
        variant="secondary"
        size="md"
        className="h-11"
        loading={pending}
        loadingText="Signing in"
        data-testid="dev-login"
        onClick={async () => {
          setPending(true)
          setError(null)
          try {
            await endpoints.devLogin('Dev user', newIdempotencyKey())
            window.location.assign(next)
          } catch (e) {
            setError(reasonText(e))
            setPending(false)
          }
        }}
      >
        Dev login
        <span className="ml-1 rounded-sm border border-line-2 px-1 text-caption font-medium text-fg-2">Dev only</span>
      </Button>
      {error ? (
        <p role="alert" className="text-caption text-state-conflict">
          {error}
        </p>
      ) : null}
    </div>
  )
}
