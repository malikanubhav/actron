/**
 * The frontend and the backend agree on the contract (spec B, B.C7): the generated OpenAPI document, the
 * connector guide check ids (spec C, C13) and the Build.report shape the request view reads.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, expectTypeOf, it } from 'vitest'
import type { components } from '@/lib/api/openapi'
import type { Evidence, PersonRef, Pr, TestPlanItem, TokenUsage } from '@/lib/api/types'
import { readBuildReport } from '@/lib/build-report'
import { DEFAULT_GUIDES } from '@/lib/connectors'

type S = components['schemas']
const root = join(__dirname, '..', '..')
const openapi = JSON.parse(readFileSync(join(root, 'lib/api/openapi.json'), 'utf8')) as {
  paths: Record<string, Record<string, unknown>>
  components: { schemas: Record<string, { properties?: Record<string, { enum?: string[] }> }> }
}
const forms = JSON.parse(readFileSync(join(root, '..', 'backend/actron/connectors/forms.json'), 'utf8')) as {
  providers: { provider: string; guide: { id: string; title: string; checkId?: string }[] }[]
}

describe('generated API types (B.C7)', () => {
  it('aliases match the generated schema exactly', () => {
    expectTypeOf<PersonRef>().toEqualTypeOf<S['PersonRef']>()
    expectTypeOf<TestPlanItem>().toEqualTypeOf<S['TestPlanItem']>()
    expectTypeOf<Pr>().toEqualTypeOf<S['Pr']>()
    expectTypeOf<TokenUsage>().toEqualTypeOf<S['Tokens']>()
    expectTypeOf<Evidence>().toEqualTypeOf<S['Evidence']>()
  })

  it('openapi.json carries every B.C7 request route', () => {
    for (const path of [
      '/api/requests',
      '/api/requests/{request_id}',
      '/api/requests/{request_id}/events',
      '/api/requests/{request_id}/answers',
      '/api/requests/{request_id}/approvals',
      '/api/connectors',
      '/api/connectors/{provider}/options',
      '/api/connectors/{provider}/checks',
      '/api/stream',
    ]) {
      expect(openapi.paths[path], path).toBeDefined()
    }
  })

  it('evidence roles in the schema are the contract roles', () => {
    expect(openapi.components.schemas.Evidence?.properties?.role?.enum).toEqual([
      'conflict',
      'constraint',
      'impact',
      'similar_work',
      'owner',
      'test',
    ])
  })
})

describe('connector guides (C-AC-54, C-AC-55)', () => {
  it('the backend serves the same C13 steps and check ids the frontend falls back to', () => {
    for (const provider of ['github', 'slack', 'linear'] as const) {
      const served = forms.providers.find((p) => p.provider === provider)?.guide
      expect(served, provider).toEqual(DEFAULT_GUIDES[provider])
    }
    expect(forms.providers.find((p) => p.provider === 'slack_export')?.guide).toEqual([])
  })

  it('every guide step names a check id', () => {
    for (const steps of Object.values(DEFAULT_GUIDES)) {
      for (const s of steps) expect(s.checkId, s.id).toBeTruthy()
    }
  })
})

describe('Build.report from the backend (B-AC-76)', () => {
  it('reads the shape flow/build.py build_ui_report writes', () => {
    const report = readBuildReport({
      tests: [
        { name: 'test_add', status: 'fail', output: 'assert 5 == -1' },
        { name: 'tests/test_ops.py::test_subtract', status: 'pass' },
      ],
      constraints: [
        { text: 'add keeps its signature', status: 'holds', proof: { kind: 'test', label: 'test_add still passes' } },
        { text: 'total stays linear', status: 'unverified', proof: null },
      ],
      filesChanged: [{ path: 'calc/ops.py', additions: 4, deletions: 0 }],
      procedures: [{ title: 'Python tests', testCommand: 'pytest -q' }],
      testsAdded: ['tests/test_ops.py::test_subtract'],
      notes: 'Added subtract next to add.',
      pi: null,
    })
    expect(report.tests.map((t) => t.status)).toEqual(['fail', 'pass'])
    expect(report.tests[0]?.output).toBe('assert 5 == -1')
    expect(report.constraints[0]).toEqual({
      text: 'add keeps its signature',
      status: 'holds',
      proof: { kind: 'test', label: 'test_add still passes', url: null },
    })
    expect(report.constraints[1]?.proof).toBeNull()
    expect(report.filesChanged).toEqual([{ path: 'calc/ops.py', additions: 4, deletions: 0 }])
    expect(report.procedures).toEqual([{ title: 'Python tests', testCommand: 'pytest -q' }])
  })
})
