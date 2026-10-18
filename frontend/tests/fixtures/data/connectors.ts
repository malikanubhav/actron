/**
 * FIXTURE: recorded-style test data for development and tests only; never used in production builds.
 *
 * Connector form definitions (spec C, C12), option lists, validation results and setup-guide checks for the
 * Calva repository (BetterThanTomorrow/calva). People and workspaces are fictional.
 */
import type {
  ConnectorCheck,
  ConnectorDefinition,
  ConnectorOption,
  ValidateResult,
} from '@/lib/api/types'

export const SLACK_MANIFEST_DEV = `display_information:
  name: Actron (dev)
  description: Checks what your team decided and built before an AI writes code. Development copy using Socket Mode.
features:
  app_home:
    home_tab_enabled: false
    messages_tab_enabled: true
    messages_tab_read_only_enabled: false
  bot_user:
    display_name: actron-dev
    always_online: true
  slash_commands:
    - command: /actron
      description: Ask Actron to check a request against your history, or ask a question.
      usage_hint: "[ask] what you need"
      should_escape: false
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - channels:history
      - channels:read
      - chat:write
      - commands
      - groups:history
      - groups:read
      - im:write
      - reactions:read
      - team:read
      - users:read
      - users:read.email
    user:
      - openid
      - profile
      - email
settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - message.channels
      - message.groups
      - member_joined_channel
      - channel_rename
      - app_uninstalled
      - tokens_revoked
  interactivity:
    is_enabled: true
  org_deploy_enabled: false
  socket_mode_enabled: true
  token_rotation_enabled: false
`

export const SLACK_BOT_SCOPES = [
  'app_mentions:read',
  'channels:history',
  'channels:read',
  'chat:write',
  'commands',
  'groups:history',
  'groups:read',
  'im:write',
  'reactions:read',
  'team:read',
  'users:read',
  'users:read.email',
] as const

export const CONNECTOR_DEFINITIONS: ConnectorDefinition[] = [
  {
    provider: 'github',
    title: 'Repository',
    label: 'SOURCE 01 · CODE',
    fields: [
      {
        field_id: 'access_token',
        type: 'string',
        required: true,
        label: 'Access token',
        description: 'A fine-grained personal access token. Actron uses it to read the repository and open pull requests.',
        ui_component: 'password',
        is_secret: true,
        placeholder: 'github_pat_…',
        info: 'GitHub → Settings → Developer settings → Fine-grained tokens. Repository access: the repository below (and the fork). Permissions: Contents read and write, Pull requests read and write, Issues read, Metadata read, Actions read, Checks read.',
      },
      {
        field_id: 'repository',
        type: 'string',
        required: true,
        label: 'Repository',
        description: 'The repository your team merges into; Actron reads its code and history. Validated live.',
        ui_component: 'text',
        placeholder: 'owner/name',
      },
      {
        field_id: 'working_branch',
        type: 'select',
        required: true,
        label: 'Working branch',
        description: 'Actron reads and keeps this branch in memory. Choose the branch your team builds on.',
        ui_component: 'select',
        dependsOn: 'repository',
        optionsFrom: 'branches',
      },
      {
        field_id: 'fork',
        type: 'string',
        required: false,
        label: 'Push to',
        description: 'Where Actron pushes branches and opens pull requests. Leave empty to use the repository. Validated for write access.',
        ui_component: 'text',
        placeholder: 'owner/name',
        dependsOn: 'repository',
      },
      {
        field_id: 'upstream',
        type: 'string',
        required: false,
        label: 'Upstream (history only)',
        description: 'Optional original repository whose PRs and issues are read for history.',
        ui_component: 'text',
        placeholder: 'owner/name',
        dependsOn: 'repository',
      },
      {
        field_id: 'history_days',
        type: 'number',
        required: false,
        label: 'History to read',
        description: 'Days of PRs, issues and reviews in the first backfill.',
        ui_component: 'stepper',
        default: 90,
        min: 7,
        max: 730,
      },
      {
        field_id: 'webhook',
        type: 'info',
        required: false,
        label: 'Instant updates',
        description:
          'Add this webhook to the repository so merges reach memory at once. Without it Actron still polls GitHub every few minutes.',
        ui_component: 'webhookPanel',
        dependsOn: 'repository',
      },
    ],
    guide: [
      { id: 'token', title: 'Create a fine-grained access token', checkId: 'token' },
      { id: 'repository', title: 'Paste the token and the repository', checkId: 'push_access' },
      { id: 'branch', title: 'Choose the working branch', checkId: 'working_branch' },
      { id: 'webhook', title: 'Add the webhook for instant updates', checkId: 'webhook_ping' },
    ],
  },
  {
    provider: 'slack',
    title: 'Slack',
    label: 'SOURCE 02 · SLACK',
    oauth: { enabled: true, url: '/api/slack/install' },
    fields: [
      {
        field_id: 'add_to_slack',
        type: 'oauth',
        required: false,
        label: 'Add to Slack',
        description: 'Approve Actron in Slack. You come back here to choose channels.',
        ui_component: 'oauthButton',
        path: 'oauth',
      },
      {
        field_id: 'manifest',
        type: 'info',
        required: false,
        label: 'Create the Slack app',
        description: 'Create a Slack app from a manifest and paste this.',
        ui_component: 'manifestPanel',
        path: 'token',
        content: SLACK_MANIFEST_DEV,
      },
      {
        field_id: 'bot_token',
        type: 'string',
        required: true,
        label: 'Bot token',
        description: 'Lets Actron read the chosen channels and post messages.',
        ui_component: 'password',
        is_secret: true,
        placeholder: 'xoxb-…',
        path: 'token',
        info: 'Your app → OAuth & Permissions → Install to Workspace → Bot User OAuth Token.',
      },
      {
        field_id: 'app_token',
        type: 'string',
        required: false,
        label: 'App-level token (for live events without a public URL)',
        description:
          'Needed when Actron runs without a public HTTPS address, for example on a laptop. Slack then sends messages, /actron commands and button clicks over Socket Mode.',
        ui_component: 'password',
        is_secret: true,
        placeholder: 'xapp-…',
        path: 'token',
        info: 'Your app → Basic Information → App-Level Tokens → Generate, scope connections:write; also turn on Socket Mode in the app settings.',
      },
      {
        field_id: 'channels',
        type: 'multiselect',
        required: true,
        label: 'Channels to read',
        description: 'Invite Actron to a channel with /invite @Actron to see it here.',
        ui_component: 'multiselect',
        dependsOn: 'bot_token',
        optionsFrom: 'channels',
        path: 'shared',
      },
      {
        field_id: 'requests_channel',
        type: 'select',
        required: false,
        label: 'Where people ask Actron',
        description: 'Default: the first selected channel. /actron works in any channel the bot is in.',
        ui_component: 'select',
        dependsOn: 'channels',
        path: 'shared',
      },
      {
        field_id: 'history_days',
        type: 'number',
        required: false,
        label: 'History to read',
        description: 'Days of messages in the first backfill.',
        ui_component: 'stepper',
        default: 90,
        min: 7,
        max: 730,
        path: 'shared',
      },
    ],
    guide: [
      { id: 'create', title: "Create the app from Actron's manifest", checkId: 'app_created' },
      { id: 'install', title: 'Install the app to your workspace', checkId: 'auth_test' },
      { id: 'socket', title: 'Turn on Socket Mode and create the app-level token', checkId: 'socket_mode' },
      { id: 'scopes', title: 'Check the permissions', checkId: 'scopes' },
      { id: 'invite', title: 'Invite Actron to your channels', checkId: 'channels' },
      { id: 'try', title: 'Try it', checkId: 'command_received' },
    ],
  },
  {
    provider: 'linear',
    title: 'Linear',
    label: 'SOURCE 03 · LINEAR',
    fields: [
      {
        field_id: 'api_key',
        type: 'string',
        required: true,
        label: 'API key',
        description: 'A personal API key. Actron reads issues and creates tickets with it.',
        ui_component: 'password',
        is_secret: true,
        placeholder: 'lin_api_…',
        info: 'Linear → Settings → Security & access → Personal API keys.',
      },
      {
        field_id: 'team',
        type: 'select',
        required: true,
        label: 'Team',
        description: 'Team whose issues Actron reads and where it creates tickets.',
        ui_component: 'select',
        dependsOn: 'api_key',
        optionsFrom: 'teams',
      },
      {
        field_id: 'ticket_label',
        type: 'select',
        required: false,
        label: "Label for Actron's tickets",
        description: 'Added to every ticket Actron creates.',
        ui_component: 'select',
        dependsOn: 'team',
        optionsFrom: 'labels',
      },
      {
        field_id: 'history_days',
        type: 'number',
        required: false,
        label: 'History to read',
        description: 'Days of issues and comments in the first backfill.',
        ui_component: 'stepper',
        default: 90,
        min: 7,
        max: 730,
      },
    ],
    guide: [
      { id: 'key', title: 'Create a personal API key', checkId: 'key_created' },
      { id: 'paste', title: 'Paste the key', checkId: 'viewer' },
      { id: 'team', title: 'Choose the team', checkId: 'team' },
    ],
  },
  {
    provider: 'slack_export',
    title: 'Slack export',
    label: 'OPTIONAL · SLACK EXPORT',
    fields: [
      {
        field_id: 'archive',
        type: 'file',
        required: true,
        label: 'Slack export',
        description: 'A workspace export (.zip, up to 200 MB). Use it instead of live Slack history. Checked for structure before import.',
        ui_component: 'file',
        accept: '.zip',
        maxSizeMb: 200,
        info: 'Workspace settings → Import/Export data → Export.',
      },
      {
        field_id: 'events',
        type: 'file',
        required: false,
        label: 'Later changes',
        description: 'Optional events (.jsonl) applied after the import.',
        ui_component: 'file',
        accept: '.jsonl',
        maxSizeMb: 200,
      },
    ],
    guide: [],
  },
]

const DAY = 86_400_000
const FIXTURE_NOW = Date.parse('2026-10-17T12:00:00Z')

export const CONNECTOR_OPTIONS: Record<string, Record<string, ConnectorOption[]>> = {
  github: {
    working_branch: [
      { value: 'dev', label: 'dev', note: 'default · last commit 2 hours ago', default: true },
      { value: 'published', label: 'published', note: 'last commit 3 days ago', protected: true },
      { value: 'master', label: 'master', note: 'last commit 9 days ago', protected: true },
      { value: 'inline-results', label: 'inline-results', note: 'last commit 12 days ago' },
      { value: 'repl-window-history', label: 'repl-window-history', note: 'last commit 21 days ago' },
    ],
  },
  slack: {
    channels: [
      { value: 'C0CALVA01', label: '#calva', note: '1,204 members' },
      { value: 'C0CALVA02', label: '#calva-dev', note: '86 members' },
      { value: 'C0CALVA03', label: '#clojure-tools', note: '412 members' },
    ],
  },
  linear: {
    team: [
      { value: 'team_cal', label: 'Calva (CAL)', default: true },
      { value: 'team_doc', label: 'Docs (DOC)' },
    ],
    ticket_label: [
      { value: 'create:actron', label: "Create label 'actron'", note: 'New label' },
      { value: 'lbl_feature', label: 'Feature' },
      { value: 'lbl_bug', label: 'Bug' },
      { value: 'lbl_repl', label: 'REPL' },
    ],
  },
}

/** Token text decides the outcome so tests can drive failures: "bad" or "revoked" fail, "readonly" cannot push. */
export function validateFixture(provider: string, values: Record<string, unknown>): ValidateResult {
  const text = (key: string) => (typeof values[key] === 'string' ? (values[key] as string) : '')
  const fail = (field: string, message: string): ValidateResult => ({
    ok: false,
    found: '',
    details: {},
    errors: [{ field, message }],
  })
  if (provider === 'github') {
    const token = text('access_token')
    if (/bad/i.test(token)) return fail('access_token', 'GitHub answered 401: the token is wrong or has expired. Create a new one and paste it again.')
    if (/revoked/i.test(token)) return fail('access_token', 'GitHub answered 401: this token was revoked. Create a new one.')
    const repo = text('repository')
    if (repo && repo.toLowerCase() !== 'betterthantomorrow/calva' && !/calva/i.test(repo))
      return fail('repository', `GitHub answered 404: ${repo} was not found, or the token cannot see it.`)
    const readonly = /readonly/i.test(token)
    return {
      ok: true,
      found: readonly
        ? 'Repository found: BetterThanTomorrow/calva, default branch dev, 1,296 PRs. The token can read but cannot push.'
        : 'Repository found: BetterThanTomorrow/calva, default branch dev, 1,296 PRs.',
      details: { defaultBranch: 'dev', pullRequests: 1296, canPush: !readonly, webhookSecret: 'whsec_fixture_4b1d9c2e7a' },
      errors: [],
    }
  }
  if (provider === 'slack') {
    const token = text('bot_token')
    if (/bad/i.test(token)) return fail('bot_token', 'Slack answered invalid_auth: the token is wrong or was revoked. Copy it again from OAuth & Permissions.')
    if (/revoked/i.test(token)) return fail('bot_token', 'Slack answered token_revoked: the app was uninstalled or the token revoked. Reinstall the app.')
    const app = text('app_token')
    if (app && /bad/i.test(app)) return fail('app_token', 'Socket Mode did not open. Turn on Socket Mode and check the app-level token has connections:write.')
    return {
      ok: true,
      found: 'Connected to Calva team (fixture) as @Actron.',
      details: { team: 'Calva team (fixture)', bot: '@Actron', socketMode: Boolean(app) },
      errors: [],
    }
  }
  if (provider === 'linear') {
    const key = text('api_key')
    if (/bad|revoked/i.test(key)) return fail('api_key', 'Linear did not accept this key. Create a new personal API key and paste it again.')
    return { ok: true, found: 'Signed in as Dana Ilić, Calva team.', details: { viewer: 'Dana Ilić', organization: 'Calva team' }, errors: [] }
  }
  return { ok: true, found: 'The export looks complete.', details: {}, errors: [] }
}

export type CheckOutcome = 'connected' | 'pending' | 'readonly' | 'missing_scope' | 'not_in_channel' | 'auth_failed'

export const MISSING_SCOPES = ['reactions:read', 'users:read.email'] as const

/** Setup-guide checks per provider and outcome (C13). */
export function checksFixture(provider: string, outcome: CheckOutcome): ConnectorCheck[] {
  const pending = (id: string, message: string): ConnectorCheck => ({ id, ok: null, message })
  const ok = (id: string, message: string): ConnectorCheck => ({ id, ok: true, message })
  if (provider === 'github') {
    if (outcome === 'pending')
      return [
        pending('token', 'Waiting for a token.'),
        pending('push_access', 'Waiting for the repository.'),
        pending('working_branch', 'Waiting for the working branch.'),
        pending('webhook_ping', 'No ping from GitHub yet.'),
      ]
    if (outcome === 'auth_failed')
      return [
        {
          id: 'token',
          ok: false,
          message: '401 Unauthorized: the token was not accepted.',
          troubleshooting: 'The token is wrong or has expired. Create a new fine-grained token and paste it again.',
        },
        pending('push_access', 'Waiting for a working token.'),
        pending('working_branch', 'Waiting for the working branch.'),
        pending('webhook_ping', 'No ping from GitHub yet.'),
      ]
    return [
      ok('token', 'Token accepted. Expires 2027-01-15.'),
      outcome === 'readonly'
        ? {
            id: 'push_access',
            ok: false,
            message: '403 Resource not accessible by personal access token: cannot push to BetterThanTomorrow/calva.',
            troubleshooting:
              'The token is missing Contents: Read and write on the push target. Edit the token, give the push target that permission, and check again.',
          }
        : ok('push_access', 'BetterThanTomorrow/calva found. The token can push branches and open pull requests.'),
      ok('working_branch', 'Working branch dev is in memory.'),
      pending('webhook_ping', 'No ping from GitHub yet. Actron polls every 5 minutes until the webhook is added.'),
    ]
  }
  if (provider === 'slack') {
    if (outcome === 'pending')
      return [
        pending('app_created', 'Waiting for the bot token.'),
        pending('auth_test', 'Waiting for the bot token.'),
        pending('socket_mode', 'Waiting for the app-level token.'),
        pending('scopes', 'Waiting for the bot token.'),
        pending('channels', 'Waiting for the bot token.'),
        pending('command_received', 'No /actron command seen yet.'),
      ]
    if (outcome === 'auth_failed')
      return [
        pending('app_created', 'Waiting for a working bot token.'),
        {
          id: 'auth_test',
          ok: false,
          message: 'invalid_auth: Slack did not accept the token.',
          troubleshooting: 'The token is wrong or was revoked. Copy it again from OAuth & Permissions.',
        },
        pending('socket_mode', 'Waiting for the app-level token.'),
        pending('scopes', 'Waiting for a working bot token.'),
        pending('channels', 'Waiting for a working bot token.'),
        pending('command_received', 'No /actron command seen yet.'),
      ]
    return [
      ok('app_created', 'The Actron app exists in Calva team (fixture).'),
      ok('auth_test', 'auth.test passed: Calva team (fixture), bot @Actron.'),
      ok('socket_mode', 'Socket Mode connection open.'),
      outcome === 'missing_scope'
        ? {
            id: 'scopes',
            ok: false,
            message: `missing_scope: ${MISSING_SCOPES.join(', ')}`,
            troubleshooting: `Missing scopes: ${MISSING_SCOPES.join(', ')}. Reinstall the app after adding these scopes.`,
          }
        : ok('scopes', 'All 12 bot scopes are granted.'),
      outcome === 'not_in_channel'
        ? {
            id: 'channels',
            ok: false,
            message: 'not_in_channel: the bot is not a member of any channel.',
            troubleshooting: 'Invite Actron with /invite @Actron.',
          }
        : ok('channels', 'Actron is in 3 channels.'),
      pending('command_received', 'No /actron command seen yet. Type /actron hello in a channel.'),
    ]
  }
  if (provider === 'linear') {
    if (outcome === 'pending')
      return [pending('key_created', 'Waiting for a key.'), pending('viewer', 'Waiting for a key.'), pending('team', 'Waiting for the team.')]
    if (outcome === 'auth_failed')
      return [
        pending('key_created', 'Waiting for a working key.'),
        {
          id: 'viewer',
          ok: false,
          message: 'AUTHENTICATION_ERROR: Linear did not accept the key.',
          troubleshooting: 'The key is wrong or was revoked. Create a new personal API key and paste it again.',
        },
        pending('team', 'Waiting for a working key.'),
      ]
    return [
      ok('key_created', 'A personal API key exists.'),
      ok('viewer', 'Signed in as Dana Ilić, Calva team.'),
      ok('team', 'Team Calva (CAL): issues readable; a dry-run ticket permission check passed.'),
    ]
  }
  return []
}

export const FIXTURE_LAST_SYNC = new Date(FIXTURE_NOW - 2 * 60_000).toISOString()
export const FIXTURE_DAY = DAY
