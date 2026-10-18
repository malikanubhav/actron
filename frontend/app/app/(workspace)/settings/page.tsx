import type { Metadata } from 'next'
import { SettingsScreen } from '@/components/settings/SettingsScreen'

export const metadata: Metadata = {
  title: 'Settings',
  description: 'Connections, sync schedules, models per job, thresholds, approvers, budget and bot identity.',
}

export default function SettingsPage() {
  return <SettingsScreen />
}
