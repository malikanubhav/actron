// FIXTURE: recorded-style test data for development and tests only; never used in production builds.
// Nine Calva requests, one per state the UI must show. Quotes and people are fictional.
import { FIXTURE_IDS } from './ids'
import { CALLERS, DECISION, FILES, FN, LINEAR, LINEAR_URL, P, PR, PR_URL, REVIEW, SLACK, SLACK_URL, TEST, catalogNode } from './graph-catalog'
import type { EvidenceSpec, RequestSpec, ToolSpec } from './spec'

export const reqNode = (id: string) => `actron:request:${id}`

function src(id: string) {
  const n = catalogNode(id)
  const props = (n?.props ?? {}) as Record<string, unknown>
  return {
    type: n?.type ?? 'Unknown',
    id,
    url: typeof props.url === 'string' ? props.url : null,
    author: typeof props.author === 'string' ? props.author : null,
    at: typeof props.at === 'string' ? props.at : typeof props.createdAt === 'string' ? props.createdAt : null,
  }
}

function quoteOf(id: string): string {
  const props = (catalogNode(id)?.props ?? {}) as Record<string, unknown>
  return String(props.text ?? props.body ?? props.quote ?? '')
}

const BASE_SHA = 'a41c9e27b3d0f5e1c8a24f6b9d0e3c7a15b2f8d4'

/* ======================================================================= live: inline results */
const LIVE = FIXTURE_IDS.live
const liveReq = reqNode(LIVE)
const liveSeed = [liveReq, FN.evaluateTopLevelForm, FN.evaluateCode]

const liveEvidence: EvidenceSpec[] = [
  {
    evidenceId: 'ev_live_results_window',
    role: 'conflict',
    nodeId: DECISION.resultsWindow,
    nodeType: 'Decision',
    title: 'Results go to the output window; inline display stays opt-in.',
    quote: quoteOf(SLACK.resultsWindow),
    source: src(SLACK.resultsWindow),
    confidence: 0.86,
    path: [...liveSeed, FN.decorateResults, DECISION.resultsWindow, SLACK.resultsWindow],
  },
  {
    evidenceId: 'ev_live_nonblocking',
    role: 'constraint',
    nodeId: DECISION.resultsNonBlocking,
    nodeType: 'Decision',
    title: 'Writing the results doc never blocks evaluation.',
    quote: quoteOf(REVIEW.resultsDocAsync),
    source: src(REVIEW.resultsDocAsync),
    confidence: 0.92,
    path: [...liveSeed, DECISION.resultsNonBlocking, REVIEW.resultsDocAsync, PR.resultsDocAsync],
  },
  {
    evidenceId: 'ev_live_pr1890',
    role: 'similar_work',
    nodeId: PR.inlineDraft,
    nodeType: 'GithubPullRequest',
    title: 'PR #1890 tried inline display and was closed.',
    quote: 'Closing this for now: inline results flicker on large outputs (CAL-188), and we agreed results stay in the output window. Happy to revisit behind a setting.',
    source: { ...src(PR.inlineDraft), author: 'Mateo Ruiz', at: '2024-10-01T07:12:00Z' },
    confidence: 0.74,
    path: [...liveSeed, FN.decorateResults, FILES.annotations, PR.inlineDraft],
  },
  {
    evidenceId: 'ev_live_impact',
    role: 'impact',
    nodeId: FN.evaluateCode,
    nodeType: 'CodeFunction',
    title: 'evaluateCode has 12 callers in 7 files and is in the 97th percentile by PageRank.',
    quote: null,
    source: src(FN.evaluateCode),
    confidence: 0.95,
    path: liveSeed,
  },
  {
    evidenceId: 'ev_live_output_name',
    role: 'constraint',
    nodeId: DECISION.outputName,
    nodeType: 'Decision',
    title: 'The output window keeps its name.',
    quote: quoteOf(SLACK.outputName),
    source: src(SLACK.outputName),
    confidence: 0.58,
    flag: true,
    path: [...liveSeed, FN.appendResult, DECISION.outputName, SLACK.outputName],
  },
  {
    evidenceId: 'ev_live_test',
    role: 'test',
    nodeId: TEST.evaluateNonBlocking,
    nodeType: 'CodeFunction',
    title: 'Test: evaluateCode does not wait for the results doc.',
    quote: null,
    source: src(TEST.evaluateNonBlocking),
    confidence: 0.88,
    path: [...liveSeed, TEST.evaluateNonBlocking],
  },
]

const liveTools: ToolSpec[] = [
  {
    tool: 'search',
    args: { query: 'inline result top-level form', types: ['CodeFunction', 'Decision'], limit: 10 },
    summary: 'Found 9 candidates; 3 are directly involved',
    nodeIds: [FN.evaluateTopLevelForm, FN.evaluateCode, FN.decorateResults],
    durationMs: 184,
  },
  {
    tool: 'find_symbol',
    args: { name: 'evaluateTopLevelForm' },
    summary: 'evaluateTopLevelForm is in src/evaluate.ts at line 262',
    nodeIds: [FN.evaluateTopLevelForm],
    durationMs: 41,
  },
  {
    tool: 'callers',
    args: { functionId: FN.evaluateCode, depth: 3 },
    summary: 'Found 12 callers in 7 files',
    nodeIds: CALLERS,
    durationMs: 233,
  },
  {
    tool: 'impact',
    args: { ids: [FN.evaluateCode, FN.decorateResults], depth: 3 },
    summary: '27 functions, 9 files and 4 tests reach this code',
    nodeIds: [...CALLERS.slice(0, 6), FN.appendResult, FN.append, TEST.evaluateTopLevel, TEST.evaluateNonBlocking],
    durationMs: 412,
  },
  {
    tool: 'criticality',
    args: { ids: [FN.evaluateCode, FN.decorateResults] },
    summary: 'evaluateCode is in the 97th percentile; decorateResults in the 71st',
    nodeIds: [FN.evaluateCode, FN.decorateResults],
    durationMs: 157,
  },
  {
    tool: 'decisions_for',
    args: { ids: [FN.evaluateCode, FN.decorateResults, FN.evaluateTopLevelForm] },
    summary: '2 decisions constrain this code; 1 more may apply',
    nodeIds: [DECISION.resultsWindow, DECISION.resultsNonBlocking, DECISION.outputName],
    durationMs: 198,
  },
  {
    tool: 'related_work',
    args: { ids: [FN.decorateResults, FN.evaluateCode] },
    summary: 'PR #1890 tried inline display and was closed; CAL-188 is still open',
    nodeIds: [PR.inlineDraft, LINEAR.flicker, PR.resultsDocAsync],
    durationMs: 176,
  },
  {
    tool: 'tests_for',
    args: { ids: [FN.evaluateCode, FN.evaluateTopLevelForm] },
    summary: '2 tests cover this code',
    nodeIds: [TEST.evaluateTopLevel, TEST.evaluateNonBlocking],
    durationMs: 88,
  },
  {
    tool: 'owners',
    args: { ids: [FN.evaluateCode, FN.decorateResults] },
    summary: 'Sam Okoro and Priya Raman know this code best',
    nodeIds: [P.sam, P.priya],
    durationMs: 102,
  },
  {
    tool: 'shortest_path',
    args: { fromId: liveReq, toId: SLACK.resultsWindow, maxHops: 6 },
    summary: 'Path of 5 hops through the output-window decision',
    nodeIds: [...liveSeed, FN.decorateResults, DECISION.resultsWindow, SLACK.resultsWindow],
    durationMs: 266,
  },
]

const liveTicket = {
  objective: 'Add an opt-in setting that shows the result of evaluating the top-level form inline, next to the form.',
  context:
    'An approved decision keeps results in the output window and inline display opt-in. evaluateCode has 12 callers and must not wait for the results doc. PR #1890 tried this before and was closed over flicker on large results.',
  acceptanceCriteria: [
    'Given calva.evaluation.showInlineResults is false (the default), when I evaluate the top-level form, then nothing is shown inline and the result goes to the output window.',
    'Given the setting is true, when I evaluate the top-level form, then the result is shown after the form and also goes to the output window.',
    'Given a result longer than 200 characters, when it is shown inline, then it is truncated with an ellipsis.',
  ],
  constraintsToPreserve: [
    { text: 'Results still go to the output window.', evidenceIds: ['ev_live_results_window'] },
    { text: 'evaluateCode never waits for the results doc write.', evidenceIds: ['ev_live_nonblocking'] },
  ],
  affectedFunctions: [FN.evaluateTopLevelForm, FN.decorateResults, FN.getConfig],
  testPlan: [
    { kind: 'existing' as const, target: TEST.evaluateNonBlocking, command: 'npm run unit-test -- --grep "does not wait for the results doc"' },
    { kind: 'new' as const, target: 'src/extension-test/unit/evaluate-test.ts', command: 'npm run unit-test -- --grep "inline result"' },
  ],
  outOfScope: ['Changing the default display', 'Flicker on large results (CAL-188)'],
  targetBranch: 'dev',
}

const DIFF_PACKAGE = `@@ -612,6 +612,12 @@
           "default": true,
           "markdownDescription": "Show evaluation results in the output window."
         },
+        "calva.evaluation.showInlineResults": {
+          "type": "boolean",
+          "default": false,
+          "markdownDescription": "Also show the result of a top-level evaluation inline, after the form."
+        },
         "calva.evaluation.inlineMaxLength": {`

const DIFF_CONFIG = `@@ -151,6 +151,7 @@ function getConfig() {
     prettyPrintingOptions: configOptions.get<PrettyPrintingOptions>('prettyPrintingOptions'),
     evaluationSendCodeToOutputWindow: configOptions.get<boolean>('evaluationSendCodeToOutputWindow'),
+    showInlineResults: configOptions.get<boolean>('evaluation.showInlineResults', false),
     enableJSCompletions: configOptions.get<boolean>('enableJSCompletions'),`

const DIFF_ANNOTATIONS = `@@ -98,9 +98,14 @@ export function decorateResults(
 export function decorateResults(
   resultString: string,
   hasError: boolean,
   codeSelection: vscode.Selection,
   editor: vscode.TextEditor
 ) {
+  if (!getConfig().showInlineResults) {
+    return;
+  }
+  const text = truncate(resultString, INLINE_MAX_LENGTH);
   const decoration = evalAnnotationDecoration(hasError ? 'error' : 'success');`

const DIFF_REPAIR = `@@ -271,8 +271,8 @@ async function evaluateTopLevelForm(
-  annotations.decorateResults(pending, false, selection, editor);
-  const result = await evaluateCode(code, options);
+  const result = await evaluateCode(code, options);
+  annotations.decorateResults(result.value, result.hasError, selection, editor);`

const liveTests = [
  'evaluates the top-level form at cursor',
  'does not wait for the results doc',
  'shows the inline result when the setting is on',
  'shows nothing inline by default',
  'truncates long inline results',
  'keeps results in the output window',
  'clears inline results on edit',
  'appends results in order',
  'reads showInlineResults from the configuration',
  'evaluates selection',
  'evaluates to cursor',
  'copies the last result',
  'decorates errors in red',
  'keeps the cursor position',
]

export const liveSpec: RequestSpec = {
  id: LIVE,
  title: 'Show evaluation results inline for the top-level form',
  text: 'Show the result of evaluating the top-level form inline, next to the form, instead of only in the output window. Keep evaluation as fast as it is today.',
  kind: 'feature',
  source: 'slack',
  requester: 'sam',
  createdAt: '2026-10-17T08:58:00Z',
  slack: { channel: 'C04CALVA01', threadTs: '1760691480.002300', permalink: SLACK_URL('1760691480.002300') },
  mode: 'agent',
  tools: liveTools,
  judgments: [
    { afterTool: 0, job: 'rank_candidates', count: 9, what: 'candidates' },
    { afterTool: 5, job: 'judge_conflict', count: 3, what: 'decisions' },
    { afterTool: 9, job: 'needs_question', count: 1, what: 'findings' },
  ],
  evidence: liveEvidence,
  label: 'conflict',
  summary: 'An approved decision keeps inline results opt-in, and evaluateCode must not wait for the results doc. Two questions before the ticket.',
  counts: { decisions: 3, relatedWork: 3, callers: 12, tests: 2 },
  questions: [
    {
      questionId: 'q_live_default',
      text: 'Inline results are opt-in by an earlier decision. Should this add a setting that is off by default, or change the default?',
      options: [
        { value: 'setting_off', label: 'Add a setting, off by default', note: 'Keeps the output-window decision', preselected: true },
        { value: 'default_on', label: 'Show inline results by default', note: 'Overrides the decision from #calva-dev, 21 Sep 2023' },
        { value: 'ask_team', label: 'Ask the team first', note: 'Actron posts the question in #calva-dev' },
      ],
      evidenceIds: ['ev_live_results_window', 'ev_live_pr1890'],
      required: true,
    },
    {
      questionId: 'q_live_branch',
      text: 'Which branch should this change go into?',
      options: [
        { value: 'dev', label: 'dev', note: "tracked by Actron's memory", preselected: true },
        { value: 'main', label: 'main', note: 'protected' },
        { value: 'new:actron/inline-top-level-results', label: 'New branch from dev', note: 'actron/inline-top-level-results' },
      ],
      evidenceIds: [],
      required: true,
    },
  ],
  tickets: [{ content: liveTicket, by: 'Actron' }],
  linear: { issueId: 'lin_fixture_214', identifier: 'CAL-214', url: LINEAR_URL('CAL-214') },
  build: {
    buildId: 'bld_live_01',
    branch: 'actron/inline-top-level-results',
    baseSha: BASE_SHA,
    headSha: '3f2a1c9e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39',
    position: 1,
    steps: [
      { text: 'Reading the ticket and the six pieces of evidence handed over' },
      { text: 'Reading evaluateTopLevelForm and decorateResults through the graph', file: 'src/evaluate.ts' },
      { text: 'Adding the setting calva.evaluation.showInlineResults', file: 'package.json', diff: DIFF_PACKAGE },
      { text: 'Reading the setting in getConfig', file: 'src/config.ts', diff: DIFF_CONFIG },
      { text: 'Showing the result inline when the setting is on', file: 'src/providers/annotations.ts', diff: DIFF_ANNOTATIONS },
      { text: 'Running the unit tests' },
    ],
    piTools: [
      { afterStep: 1, tool: 'get_code', args: { id: FN.decorateResults }, summary: 'Read decorateResults (34 lines) from snapshot a41c9e2', nodeIds: [FN.decorateResults], durationMs: 38 },
      { afterStep: 3, tool: 'references', args: { id: FN.getConfig }, summary: 'Found 41 call sites of getConfig', nodeIds: [FN.getConfig, FN.evaluateCode, FN.connect], durationMs: 121 },
    ],
    attempts: [
      {
        tests: {
          passed: 12,
          failed: 2,
          failing: [
            {
              name: 'shows the inline result when the setting is on',
              output:
                'AssertionError [ERR_ASSERTION]: Expected 1 decoration, received 0\n    at Context.<anonymous> (src/extension-test/unit/evaluate-test.ts:112:12)\n    at processImmediate (node:internal/timers:483:21)',
            },
            {
              name: 'truncates long inline results',
              output:
                "AssertionError [ERR_ASSERTION]: Expected 'abcdefghij…' but got 'pending'\n    at Context.<anonymous> (src/extension-test/unit/evaluate-test.ts:131:12)",
            },
          ],
        },
        repair: {
          reason: 'The decoration was applied before the result arrived; it now waits for the evaluation result',
          steps: [
            { text: 'Applying the decoration after the result arrives', file: 'src/evaluate.ts', diff: DIFF_REPAIR },
            { text: 'Running the unit tests again' },
          ],
        },
      },
      { tests: { passed: 14, failed: 0, failing: [] } },
    ],
    outcome: 'passed',
    tokens: { input: 182_400, output: 21_950 },
    costUsd: 1.12,
    report: {
      tests: liveTests.map((name) => ({ name, status: 'pass', durationMs: 20 + (name.length % 17) * 3 })),
      constraints: [
        { text: 'Results still go to the output window.', status: 'holds', proof: { kind: 'test', label: 'keeps results in the output window' } },
        { text: 'evaluateCode never waits for the results doc write.', status: 'holds', proof: { kind: 'test', label: 'does not wait for the results doc' } },
      ],
      filesChanged: [
        { path: 'package.json', additions: 5, deletions: 0 },
        { path: 'src/config.ts', additions: 1, deletions: 0 },
        { path: 'src/providers/annotations.ts', additions: 4, deletions: 0 },
        { path: 'src/evaluate.ts', additions: 2, deletions: 2 },
        { path: 'src/extension-test/unit/evaluate-test.ts', additions: 46, deletions: 0 },
      ],
      procedures: [{ title: 'Unit tests for evaluation', testCommand: 'npm run unit-test' }],
    },
  },
  pr: { number: 18, url: PR_URL(18), headSha: '3f2a1c9e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39', title: 'Show inline results for the top-level form behind a setting' },
  investigation: { tokens: { input: 48_210, output: 6_340 }, costUsd: 0.21 },
  writeback: { prs: 1, commits: 3, functions: 4, procedures: 1 },
}

/* ======================================================================= done: formatter alignment */
const DONE = FIXTURE_IDS.done
const doneReq = reqNode(DONE)
const doneSeed = [doneReq, FN.formatCurrentForm]

const DIFF_FORMAT = `@@ -120,12 +120,18 @@ export async function formatCurrentForm(
   const formatterConfig = await config.getConfig();
+  const alignMapValues = formatterConfig['align-map-values'] ?? false;
   const formattedInfo = formatTextAtRange(document.getText(range), {
     ...formatterConfig,
+    'align-associative?': alignMapValues,
     'keep-comments?': true,
   });`

export const doneSpec: RequestSpec = {
  id: DONE,
  title: 'Align map values when formatting the current form',
  text: 'When I format the current form, align the values in maps so they line up. Make it a setting.',
  kind: 'feature',
  source: 'slack',
  requester: 'priya',
  createdAt: '2026-10-16T09:12:00Z',
  slack: { channel: 'C04CALVA01', threadTs: '1760605920.001100', permalink: SLACK_URL('1760605920.001100') },
  mode: 'agent',
  tools: [
    { tool: 'search', args: { query: 'format current form align map', limit: 10 }, summary: 'Found 6 candidates; 2 are directly involved', nodeIds: [FN.formatCurrentForm, FN.formatRange], durationMs: 171 },
    { tool: 'callers', args: { functionId: FN.formatCurrentForm, depth: 2 }, summary: 'Found 3 callers in 2 files', nodeIds: [FN.formatRange], durationMs: 96 },
    { tool: 'decisions_for', args: { ids: [FN.formatCurrentForm] }, summary: '1 decision constrains this code', nodeIds: [DECISION.keepComments], durationMs: 133 },
    { tool: 'related_work', args: { ids: [FN.formatCurrentForm] }, summary: 'PR #1655 changed this function; CAL-142 explains why', nodeIds: [PR.keepComments, LINEAR.keepComments], durationMs: 149 },
    { tool: 'tests_for', args: { ids: [FN.formatCurrentForm] }, summary: '1 test covers this code', nodeIds: [TEST.formatKeepsComments], durationMs: 72 },
    { tool: 'owners', args: { ids: [FN.formatCurrentForm] }, summary: 'Mateo Ruiz knows this code best', nodeIds: [P.mateo], durationMs: 84 },
  ],
  judgments: [
    { afterTool: 0, job: 'rank_candidates', count: 6, what: 'candidates' },
    { afterTool: 2, job: 'judge_conflict', count: 1, what: 'decisions' },
  ],
  evidence: [
    {
      evidenceId: 'ev_done_comments',
      role: 'constraint',
      nodeId: DECISION.keepComments,
      nodeType: 'Decision',
      title: 'The formatter keeps comment forms in place.',
      quote: 'Formatting must never move or drop a (comment ...) form. People keep REPL scratch work there.',
      source: src(LINEAR.keepComments),
      confidence: 0.9,
      path: [...doneSeed, DECISION.keepComments, LINEAR.keepComments],
    },
    {
      evidenceId: 'ev_done_pr1655',
      role: 'similar_work',
      nodeId: PR.keepComments,
      nodeType: 'GithubPullRequest',
      title: 'PR #1655 changed formatCurrentForm to keep comments.',
      quote: 'Formatting the current form now passes keep-comments? through to cljfmt. Covered by the new format test.',
      source: src(PR.keepComments),
      confidence: 0.77,
      path: [...doneSeed, FILES.format, PR.keepComments],
    },
    {
      evidenceId: 'ev_done_test',
      role: 'test',
      nodeId: TEST.formatKeepsComments,
      nodeType: 'CodeFunction',
      title: 'Test: keeps comment forms in place.',
      quote: null,
      source: src(TEST.formatKeepsComments),
      confidence: 0.89,
      path: [...doneSeed, TEST.formatKeepsComments],
    },
  ],
  label: 'possible_conflict',
  summary: 'One decision constrains the formatter: comment forms stay in place. Alignment can be added behind a setting.',
  counts: { decisions: 1, relatedWork: 2, callers: 3, tests: 1 },
  questions: [
    {
      questionId: 'q_done_let',
      text: 'Should alignment also apply to let bindings, or only to maps?',
      options: [
        { value: 'maps_only', label: 'Only maps', note: 'Smallest change' },
        { value: 'maps_and_let', label: 'Maps and let bindings' },
      ],
      evidenceIds: ['ev_done_comments'],
      required: true,
      answer: { value: 'maps_only', by: 'priya', surface: 'slack' },
    },
    {
      questionId: 'q_done_branch',
      text: 'Which branch should this change go into?',
      options: [
        { value: 'dev', label: 'dev', note: "tracked by Actron's memory", preselected: true },
        { value: 'main', label: 'main', note: 'protected' },
      ],
      evidenceIds: [],
      required: true,
      answer: { value: 'dev', by: 'priya', surface: 'slack' },
    },
  ],
  tickets: [
    {
      by: 'Actron',
      content: {
        objective: 'Add a formatter setting that aligns map values when formatting the current form.',
        context: 'The formatter must keep comment forms in place (CAL-142). PR #1655 is the last change to formatCurrentForm.',
        acceptanceCriteria: [
          'Given calva.fmt.alignMapValues is true, when I format the current form, then map values line up in one column.',
          'Given the setting is false (the default), when I format, then output is unchanged.',
          'Given the form contains (comment ...), when I format, then the comment form keeps its position.',
        ],
        constraintsToPreserve: [{ text: 'Comment forms keep their place when formatting.', evidenceIds: ['ev_done_comments'] }],
        affectedFunctions: [FN.formatCurrentForm],
        testPlan: [
          { kind: 'existing', target: TEST.formatKeepsComments, command: 'npm run unit-test -- --grep "keeps comment forms"' },
          { kind: 'new', target: 'src/extension-test/unit/calva-fmt/format-test.ts', command: 'npm run unit-test -- --grep "aligns map values"' },
        ],
        outOfScope: ['Aligning let bindings'],
        targetBranch: 'dev',
      },
    },
  ],
  linear: { issueId: 'lin_fixture_201', identifier: 'CAL-201', url: LINEAR_URL('CAL-201') },
  build: {
    buildId: 'bld_done_01',
    branch: 'actron/align-map-values',
    baseSha: '9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d',
    headSha: 'c91e4b7a2d5f8e1c3b6a9d0f2e5c8b1a4d7f0e3c',
    position: 1,
    steps: [
      { text: 'Reading the ticket and the three pieces of evidence handed over' },
      { text: 'Reading formatCurrentForm through the graph', file: 'src/calva-fmt/src/format.ts' },
      { text: 'Passing align-associative? to the formatter when the setting is on', file: 'src/calva-fmt/src/format.ts', diff: DIFF_FORMAT },
      { text: 'Adding a test for aligned map values', file: 'src/extension-test/unit/calva-fmt/format-test.ts' },
      { text: 'Running the unit tests' },
    ],
    piTools: [{ afterStep: 1, tool: 'get_code', args: { id: FN.formatCurrentForm }, summary: 'Read formatCurrentForm (31 lines)', nodeIds: [FN.formatCurrentForm], durationMs: 35 }],
    attempts: [{ tests: { passed: 13, failed: 0, failing: [] } }],
    outcome: 'passed',
    tokens: { input: 96_300, output: 11_420 },
    costUsd: 0.61,
    report: {
      tests: ['keeps comment forms in place', 'aligns map values when enabled', 'leaves maps alone by default', 'formats the current form'].map((name) => ({ name, status: 'pass' })),
      constraints: [{ text: 'Comment forms keep their place when formatting.', status: 'holds', proof: { kind: 'test', label: 'keeps comment forms in place' } }],
      filesChanged: [
        { path: 'src/calva-fmt/src/format.ts', additions: 2, deletions: 0 },
        { path: 'package.json', additions: 5, deletions: 0 },
        { path: 'src/extension-test/unit/calva-fmt/format-test.ts', additions: 28, deletions: 0 },
      ],
      procedures: [{ title: 'Formatter tests', testCommand: 'npm run unit-test -- --grep format' }],
    },
  },
  pr: { number: 17, url: PR_URL(17), headSha: 'c91e4b7a2d5f8e1c3b6a9d0f2e5c8b1a4d7f0e3c', title: 'Align map values when formatting (setting)' },
  investigation: { tokens: { input: 31_880, output: 4_120 }, costUsd: 0.14 },
  writeback: { prs: 1, commits: 2, functions: 1, procedures: 1 },
}

/* ======================================================================= stale: connect timeout */
const STALE = FIXTURE_IDS.stale
const staleTicketV1 = {
  objective: 'Let people set the nREPL connect timeout in settings, keeping 30 seconds as the default.',
  context: 'An approved decision keeps 30 seconds as the default timeout. connect reads its options from getConfig.',
  acceptanceCriteria: [
    'Given calva.connectTimeoutSeconds is not set, when I connect, then the timeout is 30 seconds.',
    'Given it is set to 90, when I jack in, then Calva waits up to 90 seconds.',
  ],
  constraintsToPreserve: [{ text: 'The default stays at 30 seconds.', evidenceIds: ['ev_stale_timeout'] }],
  affectedFunctions: [FN.connect, FN.getConfig],
  testPlan: [{ kind: 'new' as const, target: 'src/extension-test/unit/nrepl/connect-test.ts', command: 'npm run unit-test -- --grep "connect timeout"' }],
  outOfScope: ['Retrying failed connections'],
  targetBranch: 'dev',
}
export const staleSpec: RequestSpec = {
  id: STALE,
  title: 'Make the nREPL connect timeout configurable',
  text: 'Big monorepos time out on the first jack-in. Let me configure the connect timeout.',
  kind: 'feature',
  source: 'ui',
  requester: 'mateo',
  createdAt: '2026-10-17T06:40:00Z',
  slack: null,
  mode: 'agent',
  tools: [
    { tool: 'search', args: { query: 'nrepl connect timeout', limit: 10 }, summary: 'Found 4 candidates; 2 are directly involved', nodeIds: [FN.connect, FN.getConfig], durationMs: 150 },
    { tool: 'decisions_for', args: { ids: [FN.connect] }, summary: '1 decision constrains this code', nodeIds: [DECISION.timeout], durationMs: 121 },
    { tool: 'callers', args: { functionId: FN.connect, depth: 2 }, summary: 'Found 2 callers in 2 files', nodeIds: [FN.jackIn], durationMs: 77 },
  ],
  judgments: [{ afterTool: 1, job: 'judge_conflict', count: 1, what: 'decisions' }],
  evidence: [
    {
      evidenceId: 'ev_stale_timeout',
      role: 'conflict',
      nodeId: DECISION.timeout,
      nodeType: 'Decision',
      title: 'The nREPL connect timeout stays at 30 seconds by default.',
      quote: quoteOf(SLACK.timeout),
      source: src(SLACK.timeout),
      confidence: 0.82,
      path: [reqNode(STALE), FN.connect, DECISION.timeout, SLACK.timeout],
    },
  ],
  label: 'conflict',
  summary: 'An approved decision fixes the default timeout at 30 seconds. A setting can change it per user.',
  counts: { decisions: 1, relatedWork: 0, callers: 2, tests: 0 },
  questions: [
    {
      questionId: 'q_stale_default',
      text: 'The default stays 30 seconds by an earlier decision. Keep 30 seconds as the default?',
      options: [
        { value: 'keep_30', label: 'Keep 30 seconds', preselected: true },
        { value: 'raise_60', label: 'Raise the default to 60 seconds', note: 'Overrides the decision' },
      ],
      evidenceIds: ['ev_stale_timeout'],
      required: true,
      answer: { value: 'keep_30', by: 'mateo', surface: 'ui' },
    },
    {
      questionId: 'q_stale_branch',
      text: 'Which branch should this change go into?',
      options: [
        { value: 'dev', label: 'dev', note: "tracked by Actron's memory", preselected: true },
        { value: 'main', label: 'main', note: 'protected' },
      ],
      evidenceIds: [],
      required: true,
      answer: { value: 'dev', by: 'mateo', surface: 'ui' },
    },
  ],
  tickets: [
    { by: 'Actron', content: staleTicketV1 },
    {
      by: 'Mateo Ruiz',
      content: {
        ...staleTicketV1,
        acceptanceCriteria: [
          ...staleTicketV1.acceptanceCriteria,
          'Given a value below 5 or above 600, when I save it, then Calva shows a warning and keeps the last valid value.',
        ],
        outOfScope: ['Retrying failed connections', 'Changing the timeout for running sessions'],
      },
    },
  ],
  linear: { issueId: 'lin_fixture_205', identifier: 'CAL-205', url: LINEAR_URL('CAL-205') },
  investigation: { tokens: { input: 18_200, output: 2_410 }, costUsd: 0.08 },
}

/* ======================================================================= building: paredit */
const BUILDING = FIXTURE_IDS.building
export const buildingSpec: RequestSpec = {
  id: BUILDING,
  title: 'Fix paredit slurp across reader conditionals',
  text: 'Forward slurp inside #?(:clj ...) pulls in the whole reader conditional instead of the next form.',
  kind: 'bug',
  source: 'ui',
  requester: 'dana',
  createdAt: '2026-10-17T07:55:00Z',
  slack: null,
  mode: 'agent',
  tools: [
    { tool: 'find_symbol', args: { name: 'forwardSlurpSexp' }, summary: 'forwardSlurpSexp is in src/cursor-doc/paredit.ts at line 512', nodeIds: [FN.forwardSlurp], durationMs: 39 },
    { tool: 'tests_for', args: { ids: [FN.forwardSlurp] }, summary: '1 test covers this code', nodeIds: [TEST.slurpReaderConditional], durationMs: 81 },
    { tool: 'decisions_for', args: { ids: [FN.forwardSlurp] }, summary: 'No decisions constrain this code', nodeIds: [], durationMs: 95 },
  ],
  judgments: [],
  evidence: [
    {
      evidenceId: 'ev_building_impact',
      role: 'impact',
      nodeId: FN.forwardSlurp,
      nodeType: 'CodeFunction',
      title: 'forwardSlurpSexp is called by 4 paredit commands.',
      quote: null,
      source: src(FN.forwardSlurp),
      confidence: 0.93,
      path: [reqNode(BUILDING), FN.forwardSlurp],
    },
    {
      evidenceId: 'ev_building_test',
      role: 'test',
      nodeId: TEST.slurpReaderConditional,
      nodeType: 'CodeFunction',
      title: 'Test: slurps across reader conditionals.',
      quote: null,
      source: src(TEST.slurpReaderConditional),
      confidence: 0.86,
      path: [reqNode(BUILDING), FN.forwardSlurp, TEST.slurpReaderConditional],
    },
  ],
  label: 'clear',
  summary: 'Nothing here conflicts with this request. One test covers the function.',
  counts: { decisions: 0, relatedWork: 0, callers: 4, tests: 1 },
  questions: [
    {
      questionId: 'q_building_branch',
      text: 'Which branch should this change go into?',
      options: [
        { value: 'dev', label: 'dev', note: "tracked by Actron's memory", preselected: true },
        { value: 'main', label: 'main', note: 'protected' },
      ],
      evidenceIds: [],
      required: true,
      answer: { value: 'dev', by: 'dana', surface: 'ui' },
    },
  ],
  tickets: [
    {
      by: 'Actron',
      content: {
        objective: 'Make forward slurp inside a reader conditional take the next form, not the whole conditional.',
        context: 'forwardSlurpSexp treats #? as an opaque token. A test exists for reader conditionals but covers only backward slurp.',
        acceptanceCriteria: ['Given the cursor in #?(:clj (a|) b), when I forward slurp, then the result is #?(:clj (a b)).'],
        constraintsToPreserve: [],
        affectedFunctions: [FN.forwardSlurp],
        testPlan: [{ kind: 'existing', target: TEST.slurpReaderConditional, command: 'npm run unit-test -- --grep "reader conditional"' }],
        outOfScope: ['Barf commands'],
        targetBranch: 'dev',
      },
    },
  ],
  linear: { issueId: 'lin_fixture_211', identifier: 'CAL-211', url: LINEAR_URL('CAL-211') },
  build: {
    buildId: 'bld_building_01',
    branch: 'actron/slurp-reader-conditional',
    baseSha: BASE_SHA,
    headSha: '',
    position: 1,
    steps: [
      { text: 'Reading the ticket and the two pieces of evidence handed over' },
      { text: 'Reading forwardSlurpSexp through the graph', file: 'src/cursor-doc/paredit.ts' },
      {
        text: 'Treating the reader conditional as a list when slurping',
        file: 'src/cursor-doc/paredit.ts',
        diff: `@@ -530,7 +530,9 @@ export function forwardSlurpSexp(
-    const next = cursor.forwardSexp();
+    const next = cursor.isReaderConditional()
+      ? cursor.forwardSexp({ skipReaderTag: true })
+      : cursor.forwardSexp();`,
      },
      { text: 'Adding a forward-slurp test for reader conditionals', file: 'src/extension-test/unit/cursor-doc/paredit-test.ts' },
    ],
    piTools: [],
    attempts: [],
    outcome: 'passed',
    tokens: { input: 64_000, output: 7_900 },
    costUsd: 0.38,
    report: {},
  },
  investigation: { tokens: { input: 9_850, output: 1_300 }, costUsd: 0.05 },
}

/* ======================================================================= failed: middleware order */
const FAILED = FIXTURE_IDS.failed
const failOutput = (n: number) =>
  `AssertionError [ERR_ASSERTION]: Expected middleware order\n  ["cider.nrepl/cider-middleware", "user/wrap-trace"]\nreceived\n  ["user/wrap-trace", "cider.nrepl/cider-middleware"]\n    at Context.<anonymous> (src/extension-test/unit/nrepl/jack-in-test.ts:${57 + n}:10)`
export const failedSpec: RequestSpec = {
  id: FAILED,
  title: 'Support custom nREPL middleware ordering in jack-in',
  text: 'Let projects choose where their own middleware goes in the jack-in middleware list.',
  kind: 'feature',
  source: 'slack',
  requester: 'sam',
  createdAt: '2026-10-16T14:05:00Z',
  slack: { channel: 'C04CALVA01', threadTs: '1760623500.000900', permalink: SLACK_URL('1760623500.000900') },
  mode: 'agent',
  tools: [
    { tool: 'search', args: { query: 'jack-in middleware order', limit: 10 }, summary: 'Found 5 candidates; 2 are directly involved', nodeIds: [FN.middlewareArgs, FN.jackIn], durationMs: 162 },
    { tool: 'decisions_for', args: { ids: [FN.middlewareArgs] }, summary: '1 decision constrains this code', nodeIds: [DECISION.middleware], durationMs: 118 },
    { tool: 'tests_for', args: { ids: [FN.middlewareArgs] }, summary: '1 test covers this code', nodeIds: [TEST.middlewareOrder], durationMs: 70 },
  ],
  judgments: [{ afterTool: 1, job: 'judge_conflict', count: 1, what: 'decisions' }],
  evidence: [
    {
      evidenceId: 'ev_failed_order',
      role: 'conflict',
      nodeId: DECISION.middleware,
      nodeType: 'Decision',
      title: 'cider-nrepl middleware loads before custom middleware.',
      quote: quoteOf(REVIEW.middlewareOrder),
      source: src(REVIEW.middlewareOrder),
      confidence: 0.91,
      path: [reqNode(FAILED), FN.middlewareArgs, DECISION.middleware, REVIEW.middlewareOrder, PR.middlewareOrder],
    },
    {
      evidenceId: 'ev_failed_test',
      role: 'test',
      nodeId: TEST.middlewareOrder,
      nodeType: 'CodeFunction',
      title: 'Test: orders cider-nrepl before custom middleware.',
      quote: null,
      source: src(TEST.middlewareOrder),
      confidence: 0.74,
      path: [reqNode(FAILED), FN.middlewareArgs, TEST.middlewareOrder],
    },
  ],
  label: 'conflict',
  summary: 'An approved decision puts cider-nrepl first. Custom order can apply after it.',
  counts: { decisions: 1, relatedWork: 1, callers: 1, tests: 1 },
  questions: [
    {
      questionId: 'q_failed_order',
      text: 'cider-nrepl loads first by an earlier decision. Should custom ordering apply only after it?',
      options: [
        { value: 'after_cider', label: 'Custom order after cider-nrepl', preselected: true },
        { value: 'fully_custom', label: 'Fully custom order', note: 'Overrides the decision' },
      ],
      evidenceIds: ['ev_failed_order'],
      required: true,
      answer: { value: 'after_cider', by: 'sam', surface: 'slack' },
    },
    {
      questionId: 'q_failed_branch',
      text: 'Which branch should this change go into?',
      options: [
        { value: 'dev', label: 'dev', note: "tracked by Actron's memory", preselected: true },
        { value: 'main', label: 'main', note: 'protected' },
      ],
      evidenceIds: [],
      required: true,
      answer: { value: 'dev', by: 'sam', surface: 'slack' },
    },
  ],
  tickets: [
    {
      by: 'Actron',
      content: {
        objective: 'Let projects order their own jack-in middleware after cider-nrepl.',
        context: 'An approved decision keeps cider-nrepl first. buildMiddlewareArgs builds the list.',
        acceptanceCriteria: [
          'Given calva.jackInMiddlewareOrder lists user/wrap-trace before user/wrap-log, when I jack in, then they load in that order after cider-nrepl.',
        ],
        constraintsToPreserve: [{ text: 'cider-nrepl middleware loads first.', evidenceIds: ['ev_failed_order'] }],
        affectedFunctions: [FN.middlewareArgs],
        testPlan: [{ kind: 'existing', target: TEST.middlewareOrder, command: 'npm run unit-test -- --grep "middleware"' }],
        outOfScope: ['Changing cider-nrepl versions'],
        targetBranch: 'dev',
      },
    },
  ],
  linear: { issueId: 'lin_fixture_207', identifier: 'CAL-207', url: LINEAR_URL('CAL-207') },
  build: {
    buildId: 'bld_failed_01',
    branch: 'actron/middleware-order',
    baseSha: BASE_SHA,
    headSha: '',
    position: 1,
    steps: [
      { text: 'Reading the ticket and the two pieces of evidence handed over' },
      { text: 'Reading buildMiddlewareArgs through the graph', file: 'src/nrepl/jack-in.ts' },
      {
        text: 'Sorting middleware by the configured order',
        file: 'src/nrepl/jack-in.ts',
        diff: `@@ -188,6 +188,8 @@ export function buildMiddlewareArgs(
   const middleware = [...cider, ...userMiddleware];
+  const order = getConfig().jackInMiddlewareOrder ?? [];
+  middleware.sort((a, b) => indexIn(order, a) - indexIn(order, b));`,
      },
      { text: 'Running the unit tests' },
    ],
    piTools: [],
    attempts: [
      {
        tests: { passed: 8, failed: 1, failing: [{ name: 'orders cider-nrepl before custom middleware', output: failOutput(0) }] },
        repair: {
          reason: 'The sort moved cider-nrepl after user middleware; sorting only the user part',
          steps: [{ text: 'Sorting only the user middleware', file: 'src/nrepl/jack-in.ts' }, { text: 'Running the unit tests again' }],
        },
      },
      {
        tests: { passed: 8, failed: 1, failing: [{ name: 'orders cider-nrepl before custom middleware', output: failOutput(4) }] },
        repair: {
          reason: 'The configured order still matches cider entries by prefix; matching exact names',
          steps: [{ text: 'Matching middleware names exactly', file: 'src/nrepl/jack-in.ts' }, { text: 'Running the unit tests again' }],
        },
      },
      { tests: { passed: 8, failed: 1, failing: [{ name: 'orders cider-nrepl before custom middleware', output: failOutput(9) }] } },
    ],
    outcome: 'failed',
    failReason: 'failed_after_repairs',
    tokens: { input: 211_700, output: 25_300 },
    costUsd: 1.31,
    report: {
      tests: [
        { name: 'orders cider-nrepl before custom middleware', status: 'fail', output: failOutput(9) },
        ...['builds args for lein', 'builds args for deps.edn', 'builds args for shadow-cljs', 'adds piggieback for cljs', 'keeps user aliases', 'quotes args on Windows', 'skips empty middleware', 'reads jackInMiddlewareOrder'].map((name) => ({ name, status: 'pass' })),
      ],
      constraints: [{ text: 'cider-nrepl middleware loads first.', status: 'broken', proof: { kind: 'test', label: 'orders cider-nrepl before custom middleware' } }],
      filesChanged: [{ path: 'src/nrepl/jack-in.ts', additions: 6, deletions: 1 }],
      procedures: [{ title: 'Jack-in tests', testCommand: 'npm run unit-test -- --grep jack-in' }],
    },
  },
  investigation: { tokens: { input: 21_400, output: 3_050 }, costUsd: 0.1 },
}

/* ======================================================================= prReady: copy results */
const PRREADY = FIXTURE_IDS.prReady
const DIFF_COPY = `@@ -433,6 +433,14 @@ export async function copyLastResultCommand() {
+export async function copyResultAtCursor() {
+  const result = outputWindow.getResultAt(vscode.window.activeTextEditor?.selection.active);
+  if (!result) {
+    void vscode.window.showInformationMessage('No evaluation result at the cursor.');
+    return;
+  }
+  await vscode.env.clipboard.writeText(result.value);
+}`
export const prReadySpec: RequestSpec = {
  id: PRREADY,
  title: 'Add copy-to-clipboard for evaluation results',
  text: 'Let me copy any result in the output window, not only the last one.',
  kind: 'feature',
  source: 'ui',
  requester: 'priya',
  createdAt: '2026-10-16T16:20:00Z',
  slack: null,
  mode: 'agent',
  tools: [
    { tool: 'search', args: { query: 'copy result clipboard', limit: 10 }, summary: 'Found 5 candidates; 2 are directly involved', nodeIds: [FN.copyLastResult, FN.appendResult], durationMs: 140 },
    { tool: 'decisions_for', args: { ids: [FN.appendResult] }, summary: 'No decisions constrain this code; 1 may apply', nodeIds: [DECISION.outputName], durationMs: 110 },
    { tool: 'related_work', args: { ids: [FN.copyLastResult] }, summary: 'CAL-209 asks for the same thing', nodeIds: [LINEAR.copyResults], durationMs: 99 },
  ],
  judgments: [{ afterTool: 1, job: 'judge_conflict', count: 1, what: 'decisions' }],
  evidence: [
    {
      evidenceId: 'ev_pr_cal209',
      role: 'similar_work',
      nodeId: LINEAR.copyResults,
      nodeType: 'LinearIssue',
      title: 'CAL-209 asks to copy results from the output window.',
      quote: 'Copying anything but the last result means selecting text by hand, and the selection includes the prompt.',
      source: src(LINEAR.copyResults),
      confidence: 0.81,
      path: [reqNode(PRREADY), FN.copyLastResult, FN.appendResult, LINEAR.copyResults],
    },
    {
      evidenceId: 'ev_pr_name',
      role: 'constraint',
      nodeId: DECISION.outputName,
      nodeType: 'Decision',
      title: 'The output window keeps its name.',
      quote: quoteOf(SLACK.outputName),
      source: src(SLACK.outputName),
      confidence: 0.55,
      flag: true,
      path: [reqNode(PRREADY), FN.copyLastResult, FN.appendResult, DECISION.outputName, SLACK.outputName],
    },
  ],
  label: 'possible_conflict',
  summary: 'CAL-209 asks for the same thing. One decision may apply: command titles keep saying "output window".',
  counts: { decisions: 1, relatedWork: 1, callers: 2, tests: 1 },
  questions: [
    {
      questionId: 'q_pr_branch',
      text: 'Which branch should this change go into?',
      options: [
        { value: 'dev', label: 'dev', note: "tracked by Actron's memory", preselected: true },
        { value: 'main', label: 'main', note: 'protected' },
      ],
      evidenceIds: [],
      required: true,
      answer: { value: 'dev', by: 'priya', surface: 'ui' },
    },
  ],
  tickets: [
    {
      by: 'Actron',
      content: {
        objective: 'Add a command that copies the evaluation result at the cursor in the output window.',
        context: 'CAL-209 asks for this. Command titles keep the name "output window".',
        acceptanceCriteria: [
          'Given the cursor is on a result in the output window, when I run "Copy result at cursor", then that result is on the clipboard.',
          'Given no result at the cursor, when I run the command, then Calva says so and copies nothing.',
        ],
        constraintsToPreserve: [{ text: 'Command titles say "output window".', evidenceIds: ['ev_pr_name'] }],
        affectedFunctions: [FN.copyLastResult, FN.appendResult],
        testPlan: [{ kind: 'new', target: 'src/extension-test/unit/evaluate-test.ts', command: 'npm run unit-test -- --grep "copies the result at cursor"' }],
        outOfScope: ['Copying from inline results'],
        targetBranch: 'dev',
      },
    },
  ],
  linear: { issueId: 'lin_fixture_209', identifier: 'CAL-209', url: LINEAR_URL('CAL-209') },
  build: {
    buildId: 'bld_pr_01',
    branch: 'actron/copy-result-at-cursor',
    baseSha: BASE_SHA,
    headSha: '7b3e9f1a5c2d8e4b6a0f3c9d1e7b5a2f8c4d6e0a',
    position: 1,
    steps: [
      { text: 'Reading the ticket and the two pieces of evidence handed over' },
      { text: 'Adding copyResultAtCursor', file: 'src/evaluate.ts', diff: DIFF_COPY },
      { text: 'Registering the command "Calva: Copy result at cursor (output window)"', file: 'package.json' },
      { text: 'Running the unit tests' },
    ],
    piTools: [{ afterStep: 0, tool: 'get_code', args: { id: FN.copyLastResult }, summary: 'Read copyLastResultCommand (19 lines)', nodeIds: [FN.copyLastResult], durationMs: 33 }],
    attempts: [{ tests: { passed: 16, failed: 0, failing: [] } }],
    outcome: 'passed',
    tokens: { input: 88_900, output: 9_740 },
    costUsd: 0.55,
    report: {
      tests: ['copies the result at cursor', 'says so when there is no result', 'copies the last result', 'keeps the clipboard on cancel'].map((name) => ({ name, status: 'pass' })),
      constraints: [{ text: 'Command titles say "output window".', status: 'holds', proof: { kind: 'evidence', label: 'package.json command title', url: null } }],
      filesChanged: [
        { path: 'src/evaluate.ts', additions: 8, deletions: 0 },
        { path: 'package.json', additions: 6, deletions: 0 },
        { path: 'src/extension-test/unit/evaluate-test.ts', additions: 31, deletions: 0 },
      ],
      procedures: [{ title: 'Unit tests for evaluation', testCommand: 'npm run unit-test' }],
    },
  },
  pr: { number: 16, url: PR_URL(16), headSha: '7b3e9f1a5c2d8e4b6a0f3c9d1e7b5a2f8c4d6e0a', title: 'Copy the evaluation result at the cursor' },
  investigation: { tokens: { input: 17_600, output: 2_200 }, costUsd: 0.07 },
}

/* ======================================================================= cancelled: rename output window */
const CANCELLED = FIXTURE_IDS.cancelled
export const cancelledSpec: RequestSpec = {
  id: CANCELLED,
  title: 'Rename the output window to REPL log',
  text: '"Output window" confuses new users. Rename it to "REPL log" everywhere.',
  kind: 'feature',
  source: 'slack',
  requester: 'mateo',
  createdAt: '2026-10-15T13:30:00Z',
  slack: { channel: 'C04CALVA01', threadTs: '1760535000.003300', permalink: SLACK_URL('1760535000.003300') },
  mode: 'pipeline',
  tools: [
    { tool: 'search', args: { query: 'output window name', limit: 10 }, summary: 'Found 7 candidates; 1 is directly involved', nodeIds: [FN.appendResult], durationMs: 133 },
    { tool: 'decisions_for', args: { ids: [FN.appendResult] }, summary: '1 decision constrains this name', nodeIds: [DECISION.outputName], durationMs: 104 },
  ],
  judgments: [{ afterTool: 1, job: 'judge_conflict', count: 1, what: 'decisions' }],
  evidence: [
    {
      evidenceId: 'ev_cancel_name',
      role: 'conflict',
      nodeId: DECISION.outputName,
      nodeType: 'Decision',
      title: 'The output window keeps its name.',
      quote: quoteOf(SLACK.outputName),
      source: src(SLACK.outputName),
      confidence: 0.94,
      path: [reqNode(CANCELLED), FN.appendResult, DECISION.outputName, SLACK.outputName],
    },
  ],
  label: 'conflict',
  summary: 'An approved decision keeps the name "output window".',
  counts: { decisions: 1, relatedWork: 0, callers: 0, tests: 0 },
  questions: [
    {
      questionId: 'q_cancel_rename',
      text: 'An earlier decision keeps the name "output window". Rename it anyway?',
      options: [
        { value: 'rename', label: 'Rename anyway', note: 'Overrides the decision' },
        { value: 'keep', label: 'Keep the name' },
      ],
      evidenceIds: ['ev_cancel_name'],
      required: true,
    },
  ],
  tickets: [],
  linear: null,
  investigation: { tokens: { input: 0, output: 0 }, costUsd: 0 },
}

/* ======================================================================= answered: Q&A */
const ANSWERED = FIXTURE_IDS.answered
export const answeredSpec: RequestSpec = {
  id: ANSWERED,
  title: 'Why does Calva print results to a separate output file?',
  text: 'Why does Calva print evaluation results to the output window file instead of next to the code?',
  kind: 'question',
  source: 'ui',
  requester: 'dana',
  createdAt: '2026-10-17T05:10:00Z',
  slack: null,
  mode: 'agent',
  tools: [
    { tool: 'search', args: { query: 'results output window why', types: ['Decision'], limit: 5 }, summary: 'Found 2 decisions', nodeIds: [DECISION.resultsWindow, DECISION.resultsNonBlocking], durationMs: 120 },
    { tool: 'get_node', args: { id: DECISION.resultsWindow }, summary: 'Read the decision and its Slack source', nodeIds: [DECISION.resultsWindow, SLACK.resultsWindow], durationMs: 31 },
    { tool: 'get_node', args: { id: DECISION.resultsNonBlocking }, summary: 'Read the decision and its review source', nodeIds: [DECISION.resultsNonBlocking, REVIEW.resultsDocAsync], durationMs: 29 },
  ],
  judgments: [],
  evidence: [
    {
      evidenceId: 'ev_ans_window',
      role: 'constraint',
      nodeId: DECISION.resultsWindow,
      nodeType: 'Decision',
      title: 'Results go to the output window; inline display stays opt-in.',
      quote: quoteOf(SLACK.resultsWindow),
      source: src(SLACK.resultsWindow),
      confidence: 0.9,
      path: [reqNode(ANSWERED), DECISION.resultsWindow, SLACK.resultsWindow],
    },
    {
      evidenceId: 'ev_ans_nonblocking',
      role: 'constraint',
      nodeId: DECISION.resultsNonBlocking,
      nodeType: 'Decision',
      title: 'Writing the results doc never blocks evaluation.',
      quote: quoteOf(REVIEW.resultsDocAsync),
      source: src(REVIEW.resultsDocAsync),
      confidence: 0.84,
      path: [reqNode(ANSWERED), DECISION.resultsNonBlocking, REVIEW.resultsDocAsync],
    },
  ],
  label: 'clear',
  summary: 'Two decisions explain the output window.',
  counts: { decisions: 2, relatedWork: 0, callers: 0, tests: 0 },
  questions: [],
  tickets: [],
  linear: null,
  investigation: { tokens: { input: 12_100, output: 1_980 }, costUsd: 0.06 },
  answer: {
    text: 'Results go to the output window because the team decided in September 2023 to keep inline results opt-in: on shared screens, inline text hides the code people point at. The output window is also written off the evaluation path, so a slow disk never blocks the REPL (review on PR #1764).',
    citationIds: ['ev_ans_window', 'ev_ans_nonblocking'],
  },
}

/* ======================================================================= nothing found */
const NOTHING = FIXTURE_IDS.nothing
export const nothingSpec: RequestSpec = {
  id: NOTHING,
  title: 'Add a status bar tooltip that names the connected REPL type',
  text: 'On dev: show the REPL type (clj, cljs, bb) in the status bar tooltip.',
  kind: 'feature',
  source: 'ui',
  requester: 'sam',
  createdAt: '2026-10-17T07:30:00Z',
  slack: null,
  mode: 'agent',
  tools: [
    { tool: 'search', args: { query: 'status bar repl type tooltip', limit: 10 }, summary: 'Found 3 candidates; 1 is directly involved', nodeIds: [FN.statusbarUpdate], durationMs: 128 },
    { tool: 'callers', args: { functionId: FN.statusbarUpdate, depth: 2 }, summary: 'Found 1 caller in 1 file', nodeIds: [FN.activate], durationMs: 61 },
    { tool: 'decisions_for', args: { ids: [FN.statusbarUpdate] }, summary: 'No decisions constrain this code', nodeIds: [], durationMs: 90 },
  ],
  judgments: [{ afterTool: 0, job: 'rank_candidates', count: 3, what: 'candidates' }],
  evidence: [
    {
      evidenceId: 'ev_nothing_impact',
      role: 'impact',
      nodeId: FN.statusbarUpdate,
      nodeType: 'CodeFunction',
      title: 'statusbar update has 1 caller.',
      quote: null,
      source: src(FN.statusbarUpdate),
      confidence: 0.9,
      path: [reqNode(NOTHING), FN.statusbarUpdate],
    },
  ],
  label: 'nothing_found',
  summary: 'Nothing in your history touches this request.',
  counts: { decisions: 0, relatedWork: 0, callers: 1, tests: 0 },
  questions: [],
  tickets: [
    {
      by: 'Actron',
      content: {
        objective: 'Name the connected REPL type in the status bar tooltip.',
        context: 'No earlier decisions or work touch the status bar tooltip.',
        acceptanceCriteria: ['Given a connected cljs REPL, when I hover the REPL status item, then the tooltip says "Connected: cljs".'],
        constraintsToPreserve: [],
        affectedFunctions: [FN.statusbarUpdate],
        testPlan: [{ kind: 'new', target: 'src/extension-test/unit/statusbar-test.ts', command: 'npm run unit-test -- --grep "status bar tooltip"' }],
        outOfScope: ['Status bar colours'],
        targetBranch: 'dev',
      },
    },
  ],
  linear: { issueId: 'lin_fixture_213', identifier: 'CAL-213', url: LINEAR_URL('CAL-213') },
  build: {
    buildId: 'bld_nothing_01',
    branch: 'actron/statusbar-repl-type',
    baseSha: BASE_SHA,
    headSha: 'e2d4f6a8c0b1d3e5f7a9c1b3d5e7f9a1c3b5d7e9',
    position: 1,
    steps: [
      { text: 'Reading the ticket and the one piece of evidence handed over' },
      { text: 'Adding the REPL type to the tooltip', file: 'src/statusbar.ts' },
      { text: 'Running the unit tests' },
    ],
    piTools: [],
    attempts: [{ tests: { passed: 9, failed: 0, failing: [] } }],
    outcome: 'passed',
    tokens: { input: 40_100, output: 4_800 },
    costUsd: 0.24,
    report: {},
  },
  pr: { number: 19, url: PR_URL(19), headSha: 'e2d4f6a8c0b1d3e5f7a9c1b3d5e7f9a1c3b5d7e9', title: 'Name the REPL type in the status bar tooltip' },
  investigation: { tokens: { input: 8_400, output: 1_100 }, costUsd: 0.04 },
}

export const SPECS: RequestSpec[] = [liveSpec, doneSpec, staleSpec, buildingSpec, failedSpec, prReadySpec, cancelledSpec, answeredSpec, nothingSpec]
