// FIXTURE: recorded-style test data for development and tests only; never used in production builds.
// MSW handlers for every route in spec B, B.C7 (connectors come from connectors-handlers.ts, owned separately).
import { http, HttpResponse, sse, type HttpHandler, type RequestHandler, type ServerSentEventMessage } from 'msw'
import type { EventEnvelope } from '@/lib/api/types'
import { connectorHandlers } from './connectors-handlers'
import { WS_KEY, getEngine } from './engine'
import type { EventType } from '@/lib/events'

type StreamEvents = { message: string } & { [K in EventType]: string }

async function readBody(request: Request): Promise<unknown> {
  const type = request.headers.get('content-type') ?? ''
  if (request.method === 'GET' || request.method === 'HEAD') return undefined
  try {
    if (type.includes('multipart/form-data')) {
      const form = await request.formData()
      const out: Record<string, unknown> = {}
      form.forEach((value, key) => {
        out[key] = typeof value === 'string' ? value : value.name
      })
      return out
    }
    const text = await request.text()
    return text ? (JSON.parse(text) as unknown) : undefined
  } catch {
    return undefined
  }
}

function lastEventId(request: Request): number | null {
  const url = new URL(request.url)
  const raw = url.searchParams.get('lastEventId') ?? request.headers.get('last-event-id')
  if (raw === null || raw === '') return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}

/** One SSE stream: replay after Last-Event-ID, then live events; `stream-drop` errors after two events once. */
function streamHandler(path: string, keyOf: (params: Record<string, string | readonly string[] | undefined>) => string) {
  return sse<StreamEvents>(path, ({ client, request, params }) => {
    const engine = getEngine()
    const key = keyOf(params)
    if (engine.scenario === 'backend-down' || !engine.hasStream(key)) {
      client.error()
      return
    }
    const { dropAfter } = engine.openStream(key)
    let sent = 0
    let closed = false
    const send = (event: EventEnvelope) => {
      if (closed) return
      client.send({ id: String(key === WS_KEY ? event.id : (event.seq ?? event.id)), event: event.type as EventType, data: JSON.stringify(event) } as ServerSentEventMessage<StreamEvents>)
      sent += 1
      if (dropAfter !== null && sent >= dropAfter) {
        closed = true
        subscription.unsubscribe()
        setTimeout(() => client.error(), 50)
      }
    }
    const subscription = engine.subscribe(key, lastEventId(request), send)
    request.signal.addEventListener('abort', () => {
      closed = true
      subscription.unsubscribe()
    })
    // Send the replay after the response is returned.
    setTimeout(() => {
      for (const event of subscription.replay) send(event)
    }, 0)
  })
}

function route(method: 'get' | 'post' | 'put' | 'patch' | 'delete', path: string): HttpHandler {
  return http[method](path, async ({ request }) => {
    const engine = getEngine()
    const url = new URL(request.url)
    const res = engine.route(request.method, `${url.pathname}${url.search}`, await readBody(request))
    if (res.status === 204) return new HttpResponse(null, { status: 204 })
    if (res.text) return HttpResponse.text(String(res.json), { status: res.status })
    return HttpResponse.json(res.json as Record<string, unknown>, { status: res.status })
  })
}

const P = '*/api'

export const handlers: RequestHandler[] = [
  ...connectorHandlers,
  streamHandler(`${P}/requests/:id/events`, (params) => String(params.id)),
  streamHandler(`${P}/stream`, () => WS_KEY),
  route('get', `${P}/me`),
  route('post', `${P}/auth/dev-login`),
  route('post', `${P}/auth/logout`),
  route('get', `${P}/auth/slack/start`),
  route('get', `${P}/health`),
  route('get', `${P}/connections`),
  route('post', `${P}/connections`),
  route('patch', `${P}/connections/:id`),
  route('delete', `${P}/connections/:id`),
  route('post', `${P}/connections/:id/sync`),
  route('post', `${P}/connections/:id/reset-cursor`),
  route('get', `${P}/ingestion/status`),
  route('get', `${P}/ingestion/runs`),
  route('post', `${P}/requests`),
  route('post', `${P}/ask`),
  route('get', `${P}/requests`),
  route('get', `${P}/requests/:id`),
  route('get', `${P}/requests/:id/replay`),
  route('post', `${P}/requests/:id/answers`),
  route('get', `${P}/requests/:id/ticket/revisions`),
  route('post', `${P}/requests/:id/ticket/revisions`),
  route('post', `${P}/requests/:id/approvals`),
  route('post', `${P}/requests/:id/feedback`),
  route('post', `${P}/requests/:id/cancel`),
  route('post', `${P}/requests/:id/retry`),
  route('post', `${P}/requests/:id/close-pr`),
  route('get', `${P}/requests/:id/pr/diff`),
  route('get', `${P}/requests/:id/builds/:buildId/log`),
  route('get', `${P}/public/replays/:id`),
  route('get', `${P}/graph/subgraph`),
  route('get', `${P}/graph/stats`),
  route('get', `${P}/graph/sample`),
  route('get', `${P}/graph/search`),
  route('get', `${P}/graph/path`),
  route('get', `${P}/graph/quick/:tool`),
  route('get', `${P}/graph/nodes/:id/neighbours`),
  route('get', `${P}/graph/nodes/:id`),
  route('get', `${P}/notifications`),
  route('post', `${P}/notifications/:id/read`),
  route('get', `${P}/settings`),
  route('put', `${P}/settings`),
  route('post', `${P}/settings/budget`),
]
