import type { Metadata } from 'next'
import { InboxScreen } from '@/components/inbox/InboxScreen'

export const metadata: Metadata = {
  title: 'Inbox',
  description: 'Everything that needs you: questions, approvals, stopped builds and pull requests.',
}

export default function InboxPage() {
  return <InboxScreen />
}
