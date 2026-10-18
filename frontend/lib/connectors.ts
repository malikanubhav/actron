/**
 * Normalises GET /api/connectors. The contract (spec B, B.C7) gives `guide: GuideStep[]`; a backend that sends a
 * guide name instead (for example "github") gets the steps of spec C, C13 for that provider, so the setup guides
 * and their progress still work. Check ids follow C13; the backend's GET /checks must use the same ids.
 */
import type { ConnectorDefinition, GuideStep } from './api/types'

export const DEFAULT_GUIDES: Record<string, GuideStep[]> = {
  github: [
    { id: 'token', title: 'Create a fine-grained access token', checkId: 'token' },
    { id: 'repository', title: 'Paste the token and the repository', checkId: 'push_access' },
    { id: 'branch', title: 'Choose the working branch', checkId: 'working_branch' },
    { id: 'webhook', title: 'Add the webhook for instant updates', checkId: 'webhook_ping' },
  ],
  slack: [
    { id: 'create', title: "Create the app from Actron's manifest", checkId: 'app_created' },
    { id: 'install', title: 'Install the app to your workspace', checkId: 'auth_test' },
    { id: 'socket', title: 'Turn on Socket Mode and create the app-level token', checkId: 'socket_mode' },
    { id: 'scopes', title: 'Check the permissions', checkId: 'scopes' },
    { id: 'invite', title: 'Invite Actron to your channels', checkId: 'channels' },
    { id: 'try', title: 'Try it', checkId: 'command_received' },
  ],
  linear: [
    { id: 'key', title: 'Create a personal API key', checkId: 'key_created' },
    { id: 'paste', title: 'Paste the key', checkId: 'viewer' },
    { id: 'team', title: 'Choose the team', checkId: 'team' },
  ],
}

export function normalizeConnectors(raw: { providers?: unknown }): { providers: ConnectorDefinition[] } {
  const list = Array.isArray(raw.providers) ? (raw.providers as Record<string, unknown>[]) : []
  return {
    providers: list.map((p) => {
      const provider = String(p.provider ?? '')
      const guide = Array.isArray(p.guide) ? (p.guide as GuideStep[]) : (DEFAULT_GUIDES[provider] ?? [])
      const fields = Array.isArray(p.fields) ? p.fields : []
      return { ...(p as unknown as ConnectorDefinition), guide, fields } as ConnectorDefinition
    }),
  }
}
