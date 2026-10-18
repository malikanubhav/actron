// FIXTURE: recorded-style test data for development and tests only; never used in production builds.
// A slice of the Calva memory graph: decisions, the Slack, GitHub and Linear sources they came from, and the code
// they constrain. Paths, PR numbers and function names follow the real repository's layout; the decisions,
// quotes and people are fictional.
import type { GraphLink, GraphNode, NodeGroup } from '@/lib/api/types'

type Props = Record<string, unknown>

export const CATALOG: Map<string, GraphNode & { props: Props }> = new Map()
export const CATALOG_LINKS: GraphLink[] = []

function node(id: string, type: string, label: string, group: NodeGroup, props: Props = {}): string {
  CATALOG.set(id, { id, type, label, group, props: { id, ...props } })
  return id
}

function link(from: string, to: string, type: string, method: string | null = null, confidence: number | null = null): void {
  CATALOG_LINKS.push({ from, to, type, method, confidence })
}

const REPO = 'https://github.com/BetterThanTomorrow/calva'
export const PR_URL = (n: number) => `${REPO}/pull/${n}`
export const LINEAR_URL = (key: string) => `https://linear.app/calva-fixture/issue/${key}`
export const SLACK_URL = (ts: string) => `https://calva-fixture.slack.com/archives/C04CALVA01/p${ts.replace('.', '')}`

/* ---------------------------------------------------------------- people */
export const P = {
  dana: node('actron:person:dana-ilic', 'Person', 'Dana Ilić', 'core', { name: 'Dana Ilić', identities: ['slack', 'github', 'linear'] }),
  sam: node('actron:person:sam-okoro', 'Person', 'Sam Okoro', 'core', { name: 'Sam Okoro', identities: ['slack', 'github'] }),
  priya: node('actron:person:priya-raman', 'Person', 'Priya Raman', 'core', { name: 'Priya Raman', identities: ['slack', 'github', 'linear'] }),
  mateo: node('actron:person:mateo-ruiz', 'Person', 'Mateo Ruiz', 'core', { name: 'Mateo Ruiz', identities: ['github', 'linear'] }),
}

/* ---------------------------------------------------------------- features */
export const F = {
  evaluation: node('actron:feature:evaluation', 'Feature', 'Evaluation and results', 'core', { name: 'Evaluation and results' }),
  formatter: node('actron:feature:formatter', 'Feature', 'Formatter', 'core', { name: 'Formatter' }),
  repl: node('actron:feature:repl-connect', 'Feature', 'REPL connect and jack-in', 'core', { name: 'REPL connect and jack-in' }),
  paredit: node('actron:feature:paredit', 'Feature', 'Paredit', 'core', { name: 'Paredit' }),
}

/* ---------------------------------------------------------------- code */
const file = (path: string, language = 'typescript') =>
  node(`code:file:${path}`, 'CodeFile', path, 'code', { path, language, url: `${REPO}/blob/dev/${path}` })
const fn = (path: string, name: string, startLine: number, extra: Props = {}) => {
  const id = node(`code:fn:${path}#${name}`, 'CodeFunction', name, 'code', {
    qualifiedName: name,
    path,
    startLine,
    endLine: startLine + 24,
    url: `${REPO}/blob/dev/${path}#L${startLine}`,
    ...extra,
  })
  link(`code:file:${path}`, id, 'CONTAINS', 'parsed', 1)
  return id
}

export const FILES = {
  evaluate: file('src/evaluate.ts'),
  resultsDoc: file('src/results-output/results-doc.ts'),
  annotations: file('src/providers/annotations.ts'),
  config: file('src/config.ts'),
  format: file('src/calva-fmt/src/format.ts'),
  paredit: file('src/cursor-doc/paredit.ts'),
  connect: file('src/nrepl/connect.ts'),
  jackIn: file('src/nrepl/jack-in.ts'),
  extension: file('src/extension.ts'),
  statusbar: file('src/statusbar.ts'),
  packageJson: file('package.json', 'json'),
  evaluateTest: file('src/extension-test/unit/evaluate-test.ts'),
  resultsDocTest: file('src/extension-test/unit/results-output/results-doc-test.ts'),
  formatTest: file('src/extension-test/unit/calva-fmt/format-test.ts'),
  pareditTest: file('src/extension-test/unit/cursor-doc/paredit-test.ts'),
  jackInTest: file('src/extension-test/unit/nrepl/jack-in-test.ts'),
}

export const FN = {
  evaluateCode: fn('src/evaluate.ts', 'evaluateCode', 71),
  evaluateSelection: fn('src/evaluate.ts', 'evaluateSelection', 214),
  evaluateTopLevelForm: fn('src/evaluate.ts', 'evaluateTopLevelForm', 262),
  evaluateCurrentForm: fn('src/evaluate.ts', 'evaluateCurrentForm', 248),
  evaluateToCursor: fn('src/evaluate.ts', 'evaluateToCursor', 301),
  copyLastResult: fn('src/evaluate.ts', 'copyLastResultCommand', 433),
  append: fn('src/results-output/results-doc.ts', 'append', 188),
  appendResult: fn('src/results-output/results-doc.ts', 'appendResult', 236),
  decorateResults: fn('src/providers/annotations.ts', 'decorateResults', 98),
  clearDecorations: fn('src/providers/annotations.ts', 'clearEvaluationDecorations', 64),
  getConfig: fn('src/config.ts', 'getConfig', 142),
  formatCurrentForm: fn('src/calva-fmt/src/format.ts', 'formatCurrentForm', 120),
  formatRange: fn('src/calva-fmt/src/format.ts', 'formatRange', 58),
  forwardSlurp: fn('src/cursor-doc/paredit.ts', 'forwardSlurpSexp', 512),
  connect: fn('src/nrepl/connect.ts', 'connect', 377),
  jackIn: fn('src/nrepl/jack-in.ts', 'jackIn', 401),
  middlewareArgs: fn('src/nrepl/jack-in.ts', 'buildMiddlewareArgs', 188),
  activate: fn('src/extension.ts', 'activate', 96),
  statusbarUpdate: fn('src/statusbar.ts', 'update', 44),
}

const test = (path: string, name: string, line: number) =>
  fn(path, name, line, { isTest: true, testCommand: 'npm run unit-test' })

export const TEST = {
  evaluateTopLevel: test('src/extension-test/unit/evaluate-test.ts', 'evaluates the top-level form at cursor', 33),
  evaluateNonBlocking: test('src/extension-test/unit/evaluate-test.ts', 'does not wait for the results doc', 88),
  resultsDocAppend: test('src/extension-test/unit/results-output/results-doc-test.ts', 'appends results in order', 21),
  formatKeepsComments: test('src/extension-test/unit/calva-fmt/format-test.ts', 'keeps comment forms in place', 140),
  slurpReaderConditional: test('src/extension-test/unit/cursor-doc/paredit-test.ts', 'slurps across reader conditionals', 902),
  middlewareOrder: test('src/extension-test/unit/nrepl/jack-in-test.ts', 'orders cider-nrepl before custom middleware', 57),
}

/** Callers of evaluateCode (depth 1 to 3), used for the impact evidence. */
export const CALLERS = [
  fn('src/evaluate.ts', 'evaluateUser', 382),
  fn('src/evaluate.ts', 'evaluateSelectionReplace', 341),
  fn('src/evaluate.ts', 'evaluateSelectionAsComment', 356),
  fn('src/evaluate.ts', 'loadFile', 455),
  fn('src/custom-snippets.ts', 'evaluateCustomCodeSnippet', 77),
  fn('src/custom-snippets.ts', 'evaluateSnippet', 131),
  fn('src/repl-window/repl-doc.ts', 'submitRepl', 214),
  fn('src/repl-window/repl-doc.ts', 'evaluateInReplWindow', 260),
  fn('src/debugger/calva-debug.ts', 'evaluateInDebugSession', 118),
  fn('src/api/repl.ts', 'evaluateCode', 31),
  fn('src/api/repl.ts', 'currentSessionEvaluate', 58),
  fn('src/testRunner.ts', 'runNamespaceTests', 204),
]

for (const caller of CALLERS) link(caller, FN.evaluateCode, 'CALLS', 'parsed', 1)
link(FN.evaluateTopLevelForm, FN.evaluateCode, 'CALLS', 'parsed', 1)
link(FN.evaluateCurrentForm, FN.evaluateCode, 'CALLS', 'parsed', 1)
link(FN.evaluateSelection, FN.evaluateCode, 'CALLS', 'parsed', 1)
link(FN.evaluateToCursor, FN.evaluateCode, 'CALLS', 'parsed', 1)
link(FN.evaluateCode, FN.appendResult, 'CALLS', 'parsed', 1)
link(FN.appendResult, FN.append, 'CALLS', 'parsed', 1)
link(FN.evaluateCode, FN.decorateResults, 'CALLS', 'parsed', 1)
link(FN.decorateResults, FN.clearDecorations, 'CALLS', 'parsed', 1)
link(FN.evaluateCode, FN.getConfig, 'CALLS', 'parsed', 1)
link(FN.copyLastResult, FN.appendResult, 'CALLS', 'parsed', 1)
link(FN.formatCurrentForm, FN.formatRange, 'CALLS', 'parsed', 1)
link(FN.jackIn, FN.middlewareArgs, 'CALLS', 'parsed', 1)
link(FN.jackIn, FN.connect, 'CALLS', 'parsed', 1)
link(FN.connect, FN.getConfig, 'CALLS', 'parsed', 1)
link(FN.activate, FN.statusbarUpdate, 'CALLS', 'parsed', 1)
link(TEST.evaluateTopLevel, FN.evaluateTopLevelForm, 'TESTS', 'parsed', 1)
link(TEST.evaluateNonBlocking, FN.evaluateCode, 'TESTS', 'parsed', 1)
link(TEST.resultsDocAppend, FN.append, 'TESTS', 'parsed', 1)
link(TEST.formatKeepsComments, FN.formatCurrentForm, 'TESTS', 'parsed', 1)
link(TEST.slurpReaderConditional, FN.forwardSlurp, 'TESTS', 'parsed', 1)
link(TEST.middlewareOrder, FN.middlewareArgs, 'TESTS', 'naming', 0.74)
link(F.evaluation, FN.evaluateCode, 'IMPLEMENTED_IN', 'jev', 0.88)
link(F.formatter, FN.formatCurrentForm, 'IMPLEMENTED_IN', 'jev', 0.9)
link(F.repl, FN.connect, 'IMPLEMENTED_IN', 'jev', 0.86)
link(F.paredit, FN.forwardSlurp, 'IMPLEMENTED_IN', 'jev', 0.83)

/* ---------------------------------------------------------------- sources */
const slack = (ts: string, label: string, author: string, at: string, text: string) =>
  node(`slack:msg:C04CALVA01:${ts}`, 'SlackMessage', label, 'slack', {
    channel: '#calva-dev',
    ts,
    author,
    at,
    text,
    url: SLACK_URL(ts),
  })

export const SLACK = {
  resultsWindow: slack(
    '1695311402.118200',
    '#calva-dev · results in the output window',
    'Priya Raman',
    '2023-09-21T15:50:02Z',
    'We keep results in the output window. Inline results stay opt-in: people pair on shared screens and the inline text hides the code they are pointing at.',
  ),
  timeout: slack(
    '1701862203.004100',
    '#calva-dev · connect timeout',
    'Sam Okoro',
    '2023-12-06T11:30:03Z',
    'Thirty seconds is the timeout we agreed on. Shorter and big monorepos fail on the first jack-in, longer and people think Calva froze.',
  ),
  outputName: slack(
    '1712052410.552900',
    '#calva-dev · output window name',
    'Dana Ilić',
    '2024-04-02T10:06:50Z',
    'Let us not rename the output window again. Half the docs, the keybinding examples and every screencast say "output window".',
  ),
  flicker: slack(
    '1726570855.330800',
    '#calva-dev · inline flicker',
    'Mateo Ruiz',
    '2024-09-17T11:00:55Z',
    'Inline results flicker when a result is larger than a few hundred lines. Opened CAL-188 for it.',
  ),
}

const pr = (n: number, title: string, state: string, author: string, at: string) =>
  node(`github:pr:BetterThanTomorrow/calva#${n}`, 'GithubPullRequest', `PR #${n} ${title}`, 'github', {
    number: n,
    title,
    state,
    author,
    createdAt: at,
    url: PR_URL(n),
  })

export const PR = {
  resultsDocAsync: pr(1764, 'Write the results doc off the evaluation path', 'merged', 'Sam Okoro', '2024-02-12T09:20:00Z'),
  middlewareOrder: pr(1702, 'Order jack-in middleware explicitly', 'merged', 'Priya Raman', '2023-11-03T14:02:00Z'),
  inlineDraft: pr(1890, 'Inline evaluation display (draft)', 'closed', 'Mateo Ruiz', '2024-09-20T08:45:00Z'),
  keepComments: pr(1655, 'Keep comment forms when formatting', 'merged', 'Mateo Ruiz', '2023-07-14T16:10:00Z'),
}

export const REVIEW = {
  resultsDocAsync: node('github:review:BetterThanTomorrow/calva#1764:2210', 'GithubReview', 'Review on PR #1764', 'github', {
    author: 'Sam Okoro',
    at: '2024-02-13T10:41:00Z',
    body: 'evaluateCode must not await the results doc write. On a slow disk it blocks the REPL for every evaluation. Fire and forget, and keep the order with the queue.',
    url: `${PR_URL(1764)}#pullrequestreview-2210`,
  }),
  middlewareOrder: node('github:review:BetterThanTomorrow/calva#1702:1988', 'GithubReview', 'Review on PR #1702', 'github', {
    author: 'Priya Raman',
    at: '2023-11-04T09:12:00Z',
    body: 'cider-nrepl has to come first. Several user middlewares assume its ops exist, and the order is part of what we document.',
    url: `${PR_URL(1702)}#pullrequestreview-1988`,
  }),
}

const issue = (key: string, title: string, state: string, at: string) =>
  node(`linear:issue:${key}`, 'LinearIssue', `${key} ${title}`, 'linear', { identifier: key, title, state, createdAt: at, url: LINEAR_URL(key) })

export const LINEAR = {
  keepComments: issue('CAL-142', 'Formatter removes (comment ...) blocks', 'Done', '2023-07-02T08:00:00Z'),
  flicker: issue('CAL-188', 'Inline results flicker on large outputs', 'Backlog', '2024-09-17T11:04:00Z'),
  copyResults: issue('CAL-209', 'Copy evaluation results from the output window', 'In Progress', '2026-10-12T09:00:00Z'),
}

/* ---------------------------------------------------------------- decisions */
const decision = (id: string, statement: string, status: string, quote: string, source: string, decidedAt: string) => {
  const d = node(`actron:decision:${id}`, 'Decision', statement, 'core', { statement, status, quote, decidedAt })
  link(d, source, 'DECIDED_IN', 'llm', 0.93)
  return d
}

export const DECISION = {
  resultsWindow: decision(
    'results-in-output-window',
    'Results go to the output window; inline display stays opt-in.',
    'approved',
    'Inline results stay opt-in: people pair on shared screens and the inline text hides the code they are pointing at.',
    SLACK.resultsWindow,
    '2023-09-21T15:50:02Z',
  ),
  resultsNonBlocking: decision(
    'results-doc-nonblocking',
    'Writing the results doc never blocks evaluation.',
    'approved',
    'evaluateCode must not await the results doc write. On a slow disk it blocks the REPL for every evaluation.',
    REVIEW.resultsDocAsync,
    '2024-02-13T10:41:00Z',
  ),
  keepComments: decision(
    'formatter-keeps-comments',
    'The formatter keeps comment forms in place.',
    'approved',
    'Formatting must never move or drop a (comment ...) form. People keep REPL scratch work there.',
    LINEAR.keepComments,
    '2023-07-02T08:30:00Z',
  ),
  timeout: decision(
    'connect-timeout-default',
    'The nREPL connect timeout stays at 30 seconds by default.',
    'approved',
    'Thirty seconds is the timeout we agreed on. Shorter and big monorepos fail on the first jack-in.',
    SLACK.timeout,
    '2023-12-06T11:30:03Z',
  ),
  middleware: decision(
    'middleware-order-fixed',
    'cider-nrepl middleware loads before custom middleware.',
    'approved',
    'cider-nrepl has to come first. Several user middlewares assume its ops exist.',
    REVIEW.middlewareOrder,
    '2023-11-04T09:12:00Z',
  ),
  outputName: decision(
    'output-window-name',
    'The output window keeps its name.',
    'approved',
    'Let us not rename the output window again. Half the docs, the keybinding examples and every screencast say "output window".',
    SLACK.outputName,
    '2024-04-02T10:06:50Z',
  ),
}

link(DECISION.resultsWindow, FN.decorateResults, 'CONSTRAINS', 'jev', 0.86)
link(DECISION.resultsWindow, FN.evaluateTopLevelForm, 'CONSTRAINS', 'jev', 0.81)
link(DECISION.resultsNonBlocking, FN.evaluateCode, 'CONSTRAINS', 'jev', 0.92)
link(DECISION.resultsNonBlocking, FN.appendResult, 'CONSTRAINS', 'jev', 0.88)
link(DECISION.keepComments, FN.formatCurrentForm, 'CONSTRAINS', 'jev', 0.9)
link(DECISION.timeout, FN.connect, 'CONSTRAINS', 'jev', 0.84)
link(DECISION.middleware, FN.middlewareArgs, 'CONSTRAINS', 'jev', 0.91)
link(DECISION.outputName, FN.appendResult, 'CONSTRAINS', 'jev', 0.58)

link(REVIEW.resultsDocAsync, PR.resultsDocAsync, 'REVIEW_OF', 'api', 1)
link(REVIEW.middlewareOrder, PR.middlewareOrder, 'REVIEW_OF', 'api', 1)
link(PR.resultsDocAsync, FILES.resultsDoc, 'TOUCHED', 'git', 1)
link(PR.resultsDocAsync, FILES.evaluate, 'TOUCHED', 'git', 1)
link(PR.middlewareOrder, FILES.jackIn, 'TOUCHED', 'git', 1)
link(PR.inlineDraft, FILES.annotations, 'TOUCHED', 'git', 1)
link(PR.inlineDraft, FILES.evaluate, 'TOUCHED', 'git', 1)
link(PR.keepComments, FILES.format, 'TOUCHED', 'git', 1)
link(LINEAR.keepComments, PR.keepComments, 'IMPLEMENTED_BY', 'reference', 1)
link(LINEAR.flicker, PR.inlineDraft, 'IMPLEMENTED_BY', 'reference', 0.95)
link(SLACK.flicker, LINEAR.flicker, 'MENTIONS', 'reference', 1)
link(P.priya, SLACK.resultsWindow, 'POSTED', 'api', 1)
link(P.sam, SLACK.timeout, 'POSTED', 'api', 1)
link(P.dana, SLACK.outputName, 'POSTED', 'api', 1)
link(P.mateo, SLACK.flicker, 'POSTED', 'api', 1)
link(P.sam, PR.resultsDocAsync, 'AUTHORED', 'api', 1)
link(P.priya, PR.middlewareOrder, 'AUTHORED', 'api', 1)
link(P.mateo, PR.inlineDraft, 'AUTHORED', 'api', 1)
link(P.mateo, PR.keepComments, 'AUTHORED', 'api', 1)
link(P.sam, FN.evaluateCode, 'KNOWS_ABOUT', 'blame', 0.72)
link(P.priya, FN.decorateResults, 'KNOWS_ABOUT', 'blame', 0.66)
link(P.mateo, FN.formatCurrentForm, 'KNOWS_ABOUT', 'blame', 0.7)

export function catalogNode(id: string): (GraphNode & { props: Props }) | undefined {
  return CATALOG.get(id)
}

/** Adds a node created by a request (the request itself, its ticket, its PR). */
export function ensureNode(id: string, type: string, label: string, group: NodeGroup, props: Props = {}): string {
  if (!CATALOG.has(id)) node(id, type, label, group, props)
  return id
}
