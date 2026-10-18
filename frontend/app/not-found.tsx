import type { Metadata } from 'next'
import { NotFoundContent } from '@/components/states/NotFound'

export const metadata: Metadata = {
  title: 'Not found',
  description: 'This page isn’t in Actron’s memory.',
}

export default function NotFound() {
  return (
    <main id="main" className="mx-auto min-h-dvh max-w-content px-4 sm:px-page">
      <NotFoundContent home="/" />
    </main>
  )
}
