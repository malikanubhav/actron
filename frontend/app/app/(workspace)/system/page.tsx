import type { Metadata } from 'next'
import { SystemScreen } from '@/components/system/SystemScreen'

export const metadata: Metadata = {
  title: 'System',
  description: 'What Actron is doing right now: graph queries, judgments, builds and syncs as they happen.',
}

export default function SystemPage() {
  return <SystemScreen />
}
