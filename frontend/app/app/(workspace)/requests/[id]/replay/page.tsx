import type { Metadata } from 'next'
import { ReplayScreen } from '@/components/replay/ReplayScreen'

export const metadata: Metadata = {
  title: 'Replay',
  description: 'Watch how Actron handled a request, step by step, from its recorded events.',
}

export default async function ReplayPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return <ReplayScreen id={id} />
}
