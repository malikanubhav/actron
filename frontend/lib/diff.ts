/** Unified diff parsing for the PR tab and the build theatre preview. */

export interface DiffRow {
  kind: 'hunk' | 'add' | 'del' | 'ctx'
  text: string
  oldNo: number | null
  newNo: number | null
}

const HUNK = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$/

export function parsePatch(patch: string): DiffRow[] {
  const rows: DiffRow[] = []
  let oldNo = 0
  let newNo = 0
  for (const line of patch.replace(/\r\n/g, '\n').split('\n')) {
    if (line.startsWith('diff --git') || line.startsWith('index ') || line.startsWith('--- ') || line.startsWith('+++ ')) continue
    const hunk = HUNK.exec(line)
    if (hunk) {
      oldNo = Number(hunk[1])
      newNo = Number(hunk[3])
      rows.push({ kind: 'hunk', text: line, oldNo: null, newNo: null })
      continue
    }
    if (line.startsWith('\\')) continue
    if (line.startsWith('+')) {
      rows.push({ kind: 'add', text: line.slice(1), oldNo: null, newNo: newNo })
      newNo += 1
    } else if (line.startsWith('-')) {
      rows.push({ kind: 'del', text: line.slice(1), oldNo: oldNo, newNo: null })
      oldNo += 1
    } else if (rows.length > 0 || line.length > 0) {
      rows.push({ kind: 'ctx', text: line.startsWith(' ') ? line.slice(1) : line, oldNo, newNo })
      oldNo += 1
      newNo += 1
    }
  }
  // Drop a trailing empty context row from a final newline.
  const last = rows[rows.length - 1]
  if (last && last.kind === 'ctx' && last.text === '') rows.pop()
  return rows
}

export function countChanges(rows: DiffRow[]): { additions: number; deletions: number } {
  let additions = 0
  let deletions = 0
  for (const r of rows) {
    if (r.kind === 'add') additions += 1
    else if (r.kind === 'del') deletions += 1
  }
  return { additions, deletions }
}

export function shikiLang(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() ?? ''
  const map: Record<string, string> = {
    ts: 'typescript',
    tsx: 'tsx',
    js: 'javascript',
    jsx: 'jsx',
    mjs: 'javascript',
    cjs: 'javascript',
    py: 'python',
    clj: 'clojure',
    cljs: 'clojure',
    cljc: 'clojure',
    edn: 'clojure',
    json: 'json',
    md: 'markdown',
    yml: 'yaml',
    yaml: 'yaml',
    css: 'css',
    html: 'html',
    go: 'go',
    rs: 'rust',
    sh: 'bash',
  }
  return map[ext] ?? 'text'
}
