import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import { CanvasBench } from './CanvasBench'
import { DEV_FIXTURES } from '@/lib/env'

export const metadata: Metadata = { title: 'Canvas benchmark', description: 'Graph canvas frame-time benchmark for tests.' }

/** Test harness for C-AC-12 (300 nodes, 600 links); exists only in dev and fixture builds. */
export default function CanvasBenchPage() {
  if (!DEV_FIXTURES && process.env.ACTRON_ENV === 'prod') notFound()
  return <CanvasBench />
}
