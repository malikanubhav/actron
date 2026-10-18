'use client'
import { useEffect } from 'react'
import { ServerErrorContent } from '@/components/states/NotFound'

export default function RootError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error)
  }, [error])
  return (
    <main id="main" className="mx-auto min-h-dvh max-w-content px-4 sm:px-page">
      <ServerErrorContent digest={error.digest} onRetry={reset} />
    </main>
  )
}
