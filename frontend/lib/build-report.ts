/**
 * Reads Build.report (spec B, B.C7 types it as `object | null`). The UI reads these optional keys; anything
 * missing renders as "not reported" rather than guessed:
 *   tests: [{name, status: "pass"|"fail"|"skip", output?, durationMs?}]
 *   constraints: [{text, status: "holds"|"broken"|"unverified", proof: {kind: "test"|"evidence", label, url?} | null}]
 *   filesChanged: [{path, additions, deletions}]
 *   procedures: [{title, testCommand}]
 */
import type { ConstraintProof } from '@/components/request/ConstraintsChecklist'
import type { TestResult } from '@/components/request/TestList'

type Obj = Record<string, unknown>
const isObj = (v: unknown): v is Obj => Boolean(v) && typeof v === 'object'

export interface BuildReport {
  tests: TestResult[]
  constraints: ConstraintProof[]
  filesChanged: { path: string; additions: number; deletions: number }[]
  procedures: { title: string; testCommand: string }[]
}

export function readBuildReport(report: unknown): BuildReport {
  const r = isObj(report) ? report : {}
  const tests = Array.isArray(r.tests)
    ? r.tests.filter(isObj).map((t) => ({
        name: String(t.name ?? 'unnamed test'),
        status: (t.status === 'fail' ? 'fail' : t.status === 'skip' ? 'skip' : 'pass') as TestResult['status'],
        output: typeof t.output === 'string' ? t.output : undefined,
        durationMs: typeof t.durationMs === 'number' ? t.durationMs : undefined,
      }))
    : []
  const constraints = Array.isArray(r.constraints)
    ? r.constraints.filter(isObj).map((c) => ({
        text: String(c.text ?? ''),
        status: (c.status === 'holds' ? 'holds' : c.status === 'broken' ? 'broken' : 'unverified') as ConstraintProof['status'],
        proof: isObj(c.proof)
          ? {
              kind: c.proof.kind === 'evidence' ? ('evidence' as const) : ('test' as const),
              label: String(c.proof.label ?? ''),
              url: typeof c.proof.url === 'string' ? c.proof.url : null,
            }
          : null,
      }))
    : []
  const filesChanged = Array.isArray(r.filesChanged)
    ? r.filesChanged.filter(isObj).map((f) => ({
        path: String(f.path ?? ''),
        additions: Number(f.additions ?? 0),
        deletions: Number(f.deletions ?? 0),
      }))
    : []
  const procedures = Array.isArray(r.procedures)
    ? r.procedures.filter(isObj).map((p) => ({ title: String(p.title ?? ''), testCommand: String(p.testCommand ?? '') }))
    : []
  return { tests, constraints, filesChanged, procedures }
}
