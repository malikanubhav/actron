// FIXTURE: recorded-style test data for development and tests only; never used in production builds.
// Pull request diffs and raw build logs, assembled from each fixture build's recorded steps.
import type { PrDiffFile } from '@/lib/api/types'
import { countChanges, parsePatch } from '@/lib/diff'
import type { RequestSpec } from './spec'

const TEST_PATCH: Record<string, string> = {
  'src/extension-test/unit/evaluate-test.ts': `@@ -108,0 +109,22 @@ describe('evaluate', () => {
+  describe('inline result', () => {
+    it('shows the inline result when the setting is on', async () => {
+      setConfig({ 'evaluation.showInlineResults': true });
+      await evaluateTopLevelForm(editor);
+      expect(decorations(editor)).toHaveLength(1);
+    });
+
+    it('shows nothing inline by default', async () => {
+      await evaluateTopLevelForm(editor);
+      expect(decorations(editor)).toHaveLength(0);
+    });
+
+    it('truncates long inline results', async () => {
+      setConfig({ 'evaluation.showInlineResults': true });
+      stubResult('a'.repeat(500));
+      await evaluateTopLevelForm(editor);
+      expect(decorationText(editor).endsWith('…')).toBe(true);
+    });
+  });`,
  'src/extension-test/unit/calva-fmt/format-test.ts': `@@ -160,0 +161,12 @@ describe('formatCurrentForm', () => {
+  it('aligns map values when enabled', async () => {
+    const result = await format('{:a 1\\n :bbb 2}', { 'align-map-values': true });
+    expect(result).toBe('{:a   1\\n :bbb 2}');
+  });
+
+  it('leaves maps alone by default', async () => {
+    const result = await format('{:a 1\\n :bbb 2}', {});
+    expect(result).toBe('{:a 1\\n :bbb 2}');
+  });`,
}

/** The PR diff for a fixture request: every step that carried a diff, plus the tests Pi wrote. */
export function prDiffFor(spec: RequestSpec): { files: PrDiffFile[]; headSha: string } {
  const build = spec.build
  if (!build || !spec.pr) return { files: [], headSha: '' }
  const byPath = new Map<string, string[]>()
  const allSteps = [...build.steps, ...build.attempts.flatMap((a) => a.repair?.steps ?? [])]
  for (const step of allSteps) {
    if (!step.file || !step.diff) continue
    byPath.set(step.file, [...(byPath.get(step.file) ?? []), step.diff])
  }
  for (const [path, patch] of Object.entries(TEST_PATCH)) {
    if (allSteps.some((s) => s.file === path) || (spec.id.includes('LIVE') && path.includes('evaluate-test'))) byPath.set(path, [patch])
  }
  const files: PrDiffFile[] = [...byPath.entries()].map(([path, patches]) => {
    const patch = patches.join('\n')
    const { additions, deletions } = countChanges(parsePatch(patch))
    return { path, status: 'modified' as const, additions, deletions, patch }
  })
  return { files, headSha: spec.pr.headSha }
}

/** Raw log text for a build (what the container printed). */
export function buildLogFor(spec: RequestSpec): string {
  const build = spec.build
  if (!build) return ''
  const lines: string[] = [
    `[actron] build ${build.buildId} for ${spec.id}`,
    `[actron] image actron-pi:fixture, network: model provider and MCP only`,
    `[actron] checkout ${build.branch} from ${build.baseSha.slice(0, 7)}`,
    `[pi] reading TASK.md (ticket and ${spec.evidence.length} evidence items)`,
  ]
  build.steps.forEach((s, i) => {
    lines.push(`[pi] step ${i + 1}: ${s.text}`)
    if (s.file) lines.push(`[pi]   edit ${s.file}`)
  })
  build.attempts.forEach((a, i) => {
    lines.push(`[test] npm run unit-test`, `[test] ${a.tests.passed} passing, ${a.tests.failed} failing`)
    for (const f of a.tests.failing) lines.push(`[test]   FAIL ${f.name}`, ...f.output.split('\n').map((l) => `[test]     ${l}`))
    if (a.repair) lines.push(`[actron] repair attempt ${i + 1}: ${a.repair.reason}`)
  })
  lines.push(
    build.outcome === 'passed' ? `[actron] build passed at ${build.headSha.slice(0, 7)}` : `[actron] build stopped: ${build.failReason ?? 'failed'}`,
    `[actron] tokens in ${build.tokens.input}, out ${build.tokens.output}, estimated $${build.costUsd.toFixed(2)}`,
  )
  return lines.join('\n')
}
