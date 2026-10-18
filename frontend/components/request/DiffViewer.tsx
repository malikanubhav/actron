'use client'
import { useEffect, useMemo, useState } from 'react'
import type { PrDiffFile } from '@/lib/api/types'
import { parsePatch, shikiLang, type DiffRow } from '@/lib/diff'
import { BrandMark, languageFor } from '../brand/BrandMark'
import { truncateMiddle } from '@/lib/format'
import { cx } from '../ui/cx'

type Token = { content: string; color?: string }
type Highlighted = Map<number, Token[]>

/** Shiki loads only when a diff is opened (code-split). Until then, and on failure, rows show plain text. */
async function highlight(rows: DiffRow[], lang: string): Promise<Highlighted> {
  const { codeToTokens } = await import('shiki')
  const code = rows.map((r) => (r.kind === 'hunk' ? '' : r.text)).join('\n')
  const result = await codeToTokens(code, { lang: lang as 'typescript', theme: 'vitesse-dark' })
  const out: Highlighted = new Map()
  result.tokens.forEach((line, i) => out.set(i, line.map((t) => ({ content: t.content, color: t.color }))))
  return out
}

function FileDiff({ file }: { file: PrDiffFile }) {
  const rows = useMemo(() => parsePatch(file.patch), [file.patch])
  const [tokens, setTokens] = useState<Highlighted | null>(null)
  const lang = shikiLang(file.path)
  useEffect(() => {
    let cancelled = false
    if (lang === 'text') return
    highlight(rows, lang)
      .then((t) => {
        if (!cancelled) setTokens(t)
      })
      .catch(() => {
        // Plain text is a complete fallback.
      })
    return () => {
      cancelled = true
    }
  }, [rows, lang])

  return (
    <div className="overflow-x-auto" data-testid="file-diff" tabIndex={0} role="region" aria-label={`Diff of ${file.path}`}>
      <table className="w-full border-collapse font-mono text-caption">
        <caption className="sr-only">Changes in {file.path}</caption>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={i}
              data-kind={row.kind}
              className={cx(
                row.kind === 'add' && 'bg-state-ok/10',
                row.kind === 'del' && 'bg-state-conflict/10',
                row.kind === 'hunk' && 'bg-ink-2 text-fg-3',
              )}
            >
              <td className="w-10 select-none px-2 text-right align-top text-fg-3 tabular">{row.oldNo ?? ''}</td>
              <td className="w-10 select-none px-2 text-right align-top text-fg-3 tabular">{row.newNo ?? ''}</td>
              <td className="w-4 select-none align-top text-fg-3" aria-hidden>
                {row.kind === 'add' ? '+' : row.kind === 'del' ? '−' : ''}
              </td>
              {/* Code keeps its lines whole; the diff block scrolls sideways instead of breaking identifiers. */}
              <td className="whitespace-pre pr-4 align-top">
                {row.kind === 'add' ? <span className="sr-only">Added: </span> : row.kind === 'del' ? <span className="sr-only">Removed: </span> : null}
                {row.kind === 'hunk' ? (
                  row.text
                ) : tokens?.get(i) ? (
                  tokens.get(i)?.map((t, j) => (
                    <span key={j} style={{ color: t.color }}>
                      {t.content}
                    </span>
                  ))
                ) : (
                  <span className="text-fg-1">{row.text}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** File list plus unified diff with syntax colours and line numbers (spec C, C2). */
export function DiffViewer({ files }: { files: PrDiffFile[] }) {
  const [active, setActive] = useState(0)
  if (files.length === 0) return <p className="text-small text-fg-3">No file changes.</p>
  const file = files[Math.min(active, files.length - 1)] as PrDiffFile
  return (
    <div className="flex flex-col gap-3" data-testid="diff-viewer">
      <ul className="flex flex-col" role="tablist" aria-label="Changed files">
        {files.map((f, i) => {
          const lang = languageFor(f.path)
          return (
            <li key={f.path} role="presentation">
              <button
                type="button"
                role="tab"
                aria-selected={i === active}
                onClick={() => setActive(i)}
                className={cx(
                  'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-caption',
                  i === active ? 'bg-ink-2 text-fg-1' : 'text-fg-2 hover:bg-ink-2',
                )}
              >
                {lang ? <BrandMark name={lang} size={12} decorative /> : <span className="size-3" />}
                <span className="min-w-0 flex-1 truncate font-mono" title={f.path}>
                  {truncateMiddle(f.path, 44)}
                </span>
                <span className="font-mono text-eyebrow text-state-ok tabular">+{f.additions}</span>
                <span className="font-mono text-eyebrow text-state-conflict tabular">−{f.deletions}</span>
              </button>
            </li>
          )
        })}
      </ul>
      <div role="tabpanel" aria-label={file.path} className="rounded-md border border-line-1">
        <FileDiff key={file.path} file={file} />
      </div>
    </div>
  )
}
