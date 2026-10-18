import type { Metadata } from 'next'
import { Suspense } from 'react'
import { GraphExplorer } from '@/components/graph/GraphExplorer'

export const metadata: Metadata = {
  title: 'Graph',
  description: 'Explore the memory: search any node, expand neighbours and see where every link came from.',
}

export default function GraphPage() {
  return (
    <Suspense>
      <GraphExplorer />
    </Suspense>
  )
}
