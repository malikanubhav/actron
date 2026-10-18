import type { Kind } from './api/types'

const QUESTION_START = /^(what|why|how|where|who|when|which|does|do|is|are|can|could|should|did|has|have)\b/i
const BUG_WORDS = /\b(bug|error|errors|crash|crashes|broken|breaks|fails|failing|failure|regression|exception|wrong|incorrect|doesn't|does not|no longer)\b/i

/** A first guess at the request kind while typing; the user can change it and the server decides finally (J7). */
export function detectKind(text: string): Kind {
  const t = text.trim()
  if (!t) return 'feature'
  if (t.endsWith('?') || QUESTION_START.test(t)) return 'question'
  if (BUG_WORDS.test(t)) return 'bug'
  return 'feature'
}

export const KIND_LABEL: Record<Kind, string> = { feature: 'FEATURE', bug: 'BUG', question: 'QUESTION' }
