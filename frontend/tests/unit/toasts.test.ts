import { beforeEach, describe, expect, it } from 'vitest'
import { AUTO_DISMISS_MS, MAX_VISIBLE, persists, toast, useToasts, visibleToasts } from '@/lib/toasts'
import { useUi } from '@/lib/store'

describe('toasts (PROMPT 8.7)', () => {
  beforeEach(() => useToasts.getState().clear())

  it('at most three are visible, newest last', () => {
    for (const t of ['a', 'b', 'c', 'd']) toast.info(t)
    const shown = visibleToasts(useToasts.getState().toasts)
    expect(MAX_VISIBLE).toBe(3)
    expect(shown.map((t) => t.title)).toEqual(['b', 'c', 'd'])
  })

  it('errors and "needs you" persist; others dismiss after 6 s', () => {
    expect(AUTO_DISMISS_MS).toBe(6000)
    expect(persists('error')).toBe(true)
    expect(persists('needs_you')).toBe(true)
    expect(persists('info')).toBe(false)
    expect(persists('success')).toBe(false)
  })

  it('pushing with an id replaces that toast; dismiss removes it', () => {
    const id = useToasts.getState().push({ id: 'x', kind: 'info', title: 'one' })
    useToasts.getState().push({ id: 'x', kind: 'success', title: 'two', delivery: 'Approved in Slack by Dana. Build started.' })
    expect(useToasts.getState().toasts).toHaveLength(1)
    expect(useToasts.getState().toasts[0]).toMatchObject({ kind: 'success', title: 'two' })
    useToasts.getState().dismiss(id)
    expect(useToasts.getState().toasts).toEqual([])
  })

  it('helpers set the kind', () => {
    toast.error('e')
    toast.needsYou('n', { action: { label: 'Open', href: '/app' } })
    toast.success('s')
    expect(useToasts.getState().toasts.map((t) => t.kind)).toEqual(['error', 'needs_you', 'success'])
  })
})

describe('UI store (spec C, C4)', () => {
  it('pins toggle as a set and clear', () => {
    useUi.getState().togglePinned(['a', 'b'])
    expect(useUi.getState().pinnedNodeIds).toEqual(['a', 'b'])
    useUi.getState().togglePinned(['a', 'b'])
    expect(useUi.getState().pinnedNodeIds).toEqual([])
    useUi.getState().togglePinned(['a'])
    useUi.getState().clearPinned()
    expect(useUi.getState().pinnedNodeIds).toEqual([])
  })

  it('remembers tabs per request, traces paths and counts signals', () => {
    useUi.getState().setTab('r1', 'build')
    expect(useUi.getState().tabByRequest.r1).toBe('build')
    useUi.getState().tracePath('e1', ['a', 'b'])
    expect(useUi.getState().pathToTrace).toEqual({ evidenceId: 'e1', path: ['a', 'b'] })
    useUi.getState().clearTrace()
    expect(useUi.getState().pathToTrace).toBeNull()
    const before = useUi.getState().approveSignal
    useUi.getState().requestApprove()
    expect(useUi.getState().approveSignal).toBe(before + 1)
  })

  it('the system strip choice is saved', () => {
    useUi.getState().setSystemStripOpen(false)
    expect(window.localStorage.getItem('actron.systemStripOpen')).toBe('0')
    expect(useUi.getState().systemStripOpen).toBe(false)
    useUi.getState().setSystemStripOpen(true)
  })
})
