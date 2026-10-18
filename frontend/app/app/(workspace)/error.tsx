'use client'
import { useEffect } from 'react'
import { ServerErrorContent } from '@/components/states/NotFound'
import { PageFrame } from '@/components/shell/PageFrame'

/** Errors inside a screen keep the rail and footer (PRD 13.9b). */
export default function WorkspaceError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error)
  }, [error])
  return (
    <PageFrame>
      <ServerErrorContent digest={error.digest} onRetry={reset} />
    </PageFrame>
  )
}
