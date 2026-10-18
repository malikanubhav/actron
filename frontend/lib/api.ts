/**
 * Browser fetch wrapper for the Actron API (spec C, C4).
 * - Same-origin `/api/...` only; Next.js rewrites proxy to the backend.
 * - Adds `X-CSRF-Token` (from GET /api/me) to every write.
 * - Adds `Idempotency-Key` to every write. One key per user action, reused when that action is retried.
 * - Turns error bodies `{error: {code, message, details}}` into a typed `ApiError`.
 */
import type { ApiErrorBody } from './api/types'

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly details: Record<string, unknown> | undefined

  constructor(code: string, message: string, status: number, details?: Record<string, unknown>) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }

  get isConflict(): boolean {
    return this.status === 409
  }
}

export class NetworkError extends Error {
  constructor(message = 'Actron did not answer. Check your connection and try again.') {
    super(message)
    this.name = 'NetworkError'
  }
}

let csrfToken: string | null = null

export function setCsrfToken(token: string | null): void {
  csrfToken = token
}

/**
 * The token for `X-CSRF-Token`: the one GET /api/me returned, else the `actron_csrf` cookie (double submit; the
 * cookie is readable on purpose). The cookie fallback matters when /api/me came from the server prefetch, where
 * the client never runs the query that records the token.
 */
export function getCsrfToken(): string | null {
  if (csrfToken) return csrfToken
  if (typeof document === 'undefined') return null
  const raw = document.cookie.split('; ').find((c) => c.startsWith('actron_csrf='))
  return raw ? decodeURIComponent(raw.slice('actron_csrf='.length)) : null
}

/** A new idempotency key for one user action. Keep it and pass it again when the same action is retried. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  // Fallback for very old runtimes; still RFC 4122 shaped.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const value = c === 'x' ? r : (r & 0x3) | 0x8
    return value.toString(16)
  })
}

export type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export interface ApiRequestOptions {
  method?: Method
  body?: unknown
  /** Required for writes. Created once per user action; reused on retry. */
  idempotencyKey?: string
  query?: Record<string, string | number | boolean | undefined | null>
  signal?: AbortSignal
  /** Retries after a network error (not after an HTTP error). Same idempotency key every time. */
  networkRetries?: number
  /** Accept text responses (raw logs). */
  as?: 'json' | 'text'
}

type FetchLike = typeof fetch
let fetchImpl: FetchLike | null = null

/** Tests inject a fake fetch. */
export function setFetch(impl: FetchLike | null): void {
  fetchImpl = impl
}

function currentFetch(): FetchLike {
  return fetchImpl ?? globalThis.fetch.bind(globalThis)
}

export function buildUrl(path: string, query?: ApiRequestOptions['query']): string {
  const base = path.startsWith('/') ? path : `/${path}`
  if (!query) return base
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${base}?${qs}` : base
}

const WRITE_METHODS: ReadonlySet<Method> = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export async function parseError(response: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody> | null = null
  try {
    body = (await response.json()) as Partial<ApiErrorBody>
  } catch {
    body = null
  }
  const error = body?.error
  if (error && typeof error.code === 'string') {
    return new ApiError(error.code, error.message ?? 'The request failed.', response.status, error.details)
  }
  const fallbackCode = response.status === 404 ? 'not_found' : response.status === 401 ? 'unauthenticated' : 'http_error'
  return new ApiError(fallbackCode, `The server answered ${response.status}.`, response.status)
}

export async function api<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const isWrite = WRITE_METHODS.has(method)
  const headers: Record<string, string> = { Accept: options.as === 'text' ? 'text/plain' : 'application/json' }
  let body: BodyInit | undefined
  if (options.body instanceof FormData) {
    body = options.body
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  if (isWrite) {
    headers['Idempotency-Key'] = options.idempotencyKey ?? newIdempotencyKey()
    const token = getCsrfToken()
    if (token) headers['X-CSRF-Token'] = token
  }
  const url = buildUrl(path, options.query)
  const retries = options.networkRetries ?? (isWrite ? 2 : 1)

  let attempt = 0
  for (;;) {
    let response: Response
    try {
      response = await currentFetch()(url, {
        method,
        headers,
        body,
        credentials: 'same-origin',
        signal: options.signal,
      })
    } catch (cause) {
      if (options.signal?.aborted) throw cause
      if (attempt >= retries) throw new NetworkError()
      attempt += 1
      await sleep(200 * 2 ** (attempt - 1))
      continue
    }
    if (!response.ok) throw await parseError(response)
    if (response.status === 204) return undefined as T
    if (options.as === 'text') return (await response.text()) as T
    const text = await response.text()
    return (text ? JSON.parse(text) : undefined) as T
  }
}

/** Plain words for the error codes in spec B, B.C7. */
export function reasonText(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case 'stale_revision':
        return 'This ticket changed since you opened it. Review the new revision, then approve again.'
      case 'stale_head':
        return 'The pull request has new commits. Review the new head, then approve again.'
      case 'external_edit':
        return 'Someone edited the ticket in Linear. Actron saved it as a new revision. Approve that one to build.'
      case 'invalid_transition':
        return 'This action is not available in the current state.'
      case 'not_an_approver':
        return 'You are not on the approvers list for this workspace.'
      case 'already_connected':
        return 'This source is already connected.'
      case 'not_finished':
        return 'This request is still running. Replays open when it is done.'
      default:
        return error.message
    }
  }
  if (error instanceof NetworkError) return error.message
  if (error instanceof Error) return error.message
  return 'Something went wrong.'
}
