/** UI-only state (spec C, C4). Nothing from the server lives here. */
import { create } from 'zustand'
import type { SubgraphMode } from './query-keys'
import type { StreamStatus } from './stream/connection'

export type RequestTab = 'evidence' | 'questions' | 'ticket' | 'build' | 'pr'

interface UiState {
  selectedNodeId: string | null
  hoverNodeIds: string[]
  pinnedNodeIds: string[]
  canvasMode: SubgraphMode
  canvasView: 'canvas' | 'list'
  pathToTrace: { evidenceId: string; path: string[] } | null
  paletteOpen: boolean
  shortcutsOpen: boolean
  systemStripOpen: boolean
  guideOpen: string | null
  tabByRequest: Record<string, RequestTab>
  replay: { position: number; playing: boolean; speed: number }
  workspaceStream: StreamStatus
  /** Incremented by the `a` shortcut and the palette; the Request page opens its approval confirmation. */
  approveSignal: number
  /** Incremented by `n`; Home focuses its composer (other screens navigate to Home first). */
  composeSignal: number
  requestApprove: () => void
  requestCompose: () => void
  setSelectedNode: (id: string | null) => void
  setHover: (ids: string[]) => void
  togglePinned: (ids: string[]) => void
  clearPinned: () => void
  setCanvasMode: (mode: SubgraphMode) => void
  setCanvasView: (view: 'canvas' | 'list') => void
  tracePath: (evidenceId: string, path: string[]) => void
  clearTrace: () => void
  setPaletteOpen: (open: boolean) => void
  setShortcutsOpen: (open: boolean) => void
  setSystemStripOpen: (open: boolean) => void
  setGuideOpen: (provider: string | null) => void
  setTab: (requestId: string, tab: RequestTab) => void
  setReplay: (patch: Partial<UiState['replay']>) => void
  setWorkspaceStream: (status: StreamStatus) => void
}

const STRIP_KEY = 'actron.systemStripOpen'

export function readStrip(): boolean {
  try {
    if (typeof window === 'undefined') return false
    const raw = window.localStorage.getItem(STRIP_KEY)
    return raw === '1'
  } catch {
    return false
  }
}

export const useUi = create<UiState>((set) => ({
  selectedNodeId: null,
  hoverNodeIds: [],
  pinnedNodeIds: [],
  canvasMode: 'aggregated',
  canvasView: 'canvas',
  pathToTrace: null,
  paletteOpen: false,
  shortcutsOpen: false,
  // Collapsed to one caption line by default; the Request page reads a saved choice to open the map after mount.
  systemStripOpen: false,
  guideOpen: null,
  tabByRequest: {},
  replay: { position: 0, playing: false, speed: 1 },
  workspaceStream: 'connecting',
  approveSignal: 0,
  composeSignal: 0,
  requestApprove: () => set((s) => ({ approveSignal: s.approveSignal + 1 })),
  requestCompose: () => set((s) => ({ composeSignal: s.composeSignal + 1 })),
  setSelectedNode: (id) => set({ selectedNodeId: id }),
  setHover: (ids) => set({ hoverNodeIds: ids }),
  togglePinned: (ids) =>
    set((s) => {
      const allPinned = ids.every((id) => s.pinnedNodeIds.includes(id))
      return {
        pinnedNodeIds: allPinned ? s.pinnedNodeIds.filter((id) => !ids.includes(id)) : Array.from(new Set([...s.pinnedNodeIds, ...ids])),
      }
    }),
  clearPinned: () => set({ pinnedNodeIds: [] }),
  setCanvasMode: (canvasMode) => set({ canvasMode }),
  setCanvasView: (canvasView) => set({ canvasView }),
  tracePath: (evidenceId, path) => set({ pathToTrace: { evidenceId, path } }),
  clearTrace: () => set({ pathToTrace: null }),
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
  setShortcutsOpen: (shortcutsOpen) => set({ shortcutsOpen }),
  setSystemStripOpen: (systemStripOpen) => {
    try {
      window.localStorage.setItem(STRIP_KEY, systemStripOpen ? '1' : '0')
    } catch {
      // Storage can be unavailable (private mode); the strip still toggles for this visit.
    }
    set({ systemStripOpen })
  },
  setGuideOpen: (guideOpen) => set({ guideOpen }),
  setTab: (requestId, tab) => set((s) => ({ tabByRequest: { ...s.tabByRequest, [requestId]: tab } })),
  setReplay: (patch) => set((s) => ({ replay: { ...s.replay, ...patch } })),
  setWorkspaceStream: (workspaceStream) => set({ workspaceStream }),
}))
