/** Setup-guide panel state, kept for the visit so a guide reopens where it was left (C-AC-57). */
import { create } from 'zustand'

interface GuideState {
  open: string | null
  /** The step the user last opened, per provider. */
  expanded: Record<string, string | null>
  /** Panel scroll position, per provider. */
  scroll: Record<string, number>
  setOpen: (provider: string | null) => void
  setExpanded: (provider: string, stepId: string | null) => void
  setScroll: (provider: string, top: number) => void
  reset: () => void
}

export const useGuideStore = create<GuideState>((set) => ({
  open: null,
  expanded: {},
  scroll: {},
  setOpen: (open) => set({ open }),
  setExpanded: (provider, stepId) => set((s) => ({ expanded: { ...s.expanded, [provider]: stepId } })),
  setScroll: (provider, top) => set((s) => ({ scroll: { ...s.scroll, [provider]: top } })),
  reset: () => set({ open: null, expanded: {}, scroll: {} }),
}))
