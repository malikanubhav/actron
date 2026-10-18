import { toolCallLabel, shortArgs, toolGlyph, plainReason, plainSummary } from '@/lib/events'
import { formatDuration } from '@/lib/format'
import { Glyph } from '../glyphs/Glyph'
import { BrandMark } from '../brand/BrandMark'
import { Tooltip } from '../ui/Tooltip'
import { cx } from '../ui/cx'

export interface ToolCall {
  callId: string
  tool: string
  args: Record<string, unknown>
  by: 'investigator' | 'pi'
  at: string
}

export interface ToolResult {
  ok: boolean
  summary: string
  nodeIds: string[]
  durationMs: number
  error?: string
}

/**
 * One MCP graph tool call: glyph, name, arguments in mono (truncated, full text on hover), result summary and
 * duration. While running it shows a thin indeterminate bar (PRD 13.9a, "the agent choosing tools").
 */
export function ToolCallCard({ call, result, compact = false }: { call: ToolCall; result?: ToolResult; compact?: boolean }) {
  const running = !result
  const args = shortArgs(call.args)
  const fullArgs = JSON.stringify(call.args)
  return (
    <div
      data-testid="tool-call-card"
      data-state={running ? 'running' : result.ok ? 'ok' : 'failed'}
      className={cx(
        'relative flex flex-col gap-1 overflow-hidden rounded-md border bg-ink-1 px-3 py-2',
        running ? 'border-state-running/40' : result.ok ? 'border-line-1' : 'border-state-conflict/40',
      )}
    >
      <div className="flex items-center gap-2">
        {/* In the timeline the row already shows the tool's glyph; the card does not repeat it. */}
        {!compact ? (
          <span className={cx('shrink-0', running ? 'text-state-running' : 'text-fg-2')}>
            <Glyph name={toolGlyph(call.tool)} size={16} animated={running} />
          </span>
        ) : null}
        <span className="text-caption font-medium text-fg-3">{call.by === 'pi' ? 'Pi · graph tool' : 'Graph tool'}</span>
        {!compact ? (
          <span title="Called over MCP, the protocol Actron's graph tools use" className="inline-flex text-fg-3">
            <BrandMark name="mcp" size={12} tone="mono" decorative />
          </span>
        ) : null}
        <span className="flex-1" />
        {result ? (
          <span className="font-mono text-eyebrow text-fg-3 tabular">{formatDuration(result.durationMs)}</span>
        ) : (
          <span className="text-caption font-medium text-state-running">Running</span>
        )}
      </div>
      {compact ? (
        // Inside a focusable timeline row: no nested focus target; the full call shows as a native title.
        <code title={`${call.tool}(${fullArgs})`} className="line-clamp-2 break-words font-mono text-caption text-fg-1">
          <span className="font-medium text-fg-1">{call.tool}</span>
          <span className="text-fg-3">(</span>
          {args}
          <span className="text-fg-3">)</span>
        </code>
      ) : (
        <Tooltip content={<span className="font-mono break-all">{call.tool}({fullArgs})</span>}>
          <code tabIndex={0} className="block truncate font-mono text-caption text-fg-1" aria-label={toolCallLabel(call.tool, call.args)}>
            <span className="font-medium text-fg-1">{call.tool}</span>
            <span className="text-fg-3">(</span>
            {args}
            <span className="text-fg-3">)</span>
          </code>
        </Tooltip>
      )}
      {result ? (
        <p className={cx('text-small', result.ok ? 'text-fg-2' : 'text-state-conflict')}>
          {!compact ? <span aria-hidden className="mr-1 text-fg-3">→</span> : null}
          {result.ok ? plainSummary(result.summary) : `Failed: ${result.error ? plainReason(result.error) : 'no reason given'}`}
        </p>
      ) : null}
      {running ? (
        <span aria-hidden className="absolute inset-x-0 bottom-0 h-px overflow-hidden">
          <span className="progress-indeterminate block h-px w-1/3 bg-state-running" />
        </span>
      ) : null}
    </div>
  )
}
