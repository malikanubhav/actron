/** Journey screenshot paths, written by scripts/capture-screens.ts from the running app. */
export const JOURNEY_FILES = [1, 2, 3, 4, 5].map((n) => `/landing/journey-0${n}.png`)

/**
 * "Watch a replay" target (C-AC-47): the newest finished request. Public replay when the workspace allows it,
 * otherwise the in-app replay (which asks the visitor to sign in). Null when no finished request exists.
 */
export function replayHref(requestId: string | null, publicAllowed: boolean): string | null {
  if (!requestId) return null
  return publicAllowed ? `/replay/${encodeURIComponent(requestId)}` : `/app/requests/${encodeURIComponent(requestId)}/replay`
}
