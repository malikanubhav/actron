/**
 * The problem as geometry: one shared function, two callers, and a decision the agent never saw. A new change
 * satisfies the request and breaks the second caller.
 */
export function ProblemIllustration({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 560 300"
      role="img"
      aria-labelledby="problem-illustration-title"
      className={className}
      data-testid="problem-illustration"
    >
      <title id="problem-illustration-title">
        A shared function with two callers. An earlier decision about it is not in the agent&apos;s context, so a new change breaks
        the second caller.
      </title>
      <g fill="none" strokeLinecap="round" strokeWidth="1.5">
        {/* Callers */}
        <path d="M150 74 L262 140" className="stroke-fg-3" />
        <path d="M150 226 L262 160" className="stroke-state-conflict" />
        {/* Forgotten decision */}
        <path d="M412 76 L318 140" className="stroke-fg-3" strokeDasharray="4 6" />
        {/* The new request */}
        <path d="M416 196 L314 160" className="stroke-fg-2" />
        <path d="M323 158 L314 160 L320 167" className="stroke-fg-2" />
      </g>
      {/* Shared function */}
      <circle cx="290" cy="150" r="22" className="fill-node-code" />
      {/* Low enough that neither the red caller line nor the request line crosses the label */}
      <text x="290" y="214" textAnchor="middle" className="fill-fg-1 font-mono" fontSize="12">
        formatCurrentForm()
      </text>
      <text x="290" y="230" textAnchor="middle" className="fill-fg-3" fontSize="11">
        Shared function
      </text>
      {/* Callers */}
      <circle cx="140" cy="68" r="9" className="fill-node-code" opacity="0.7" />
      <text x="124" y="48" textAnchor="middle" className="fill-fg-2" fontSize="12">
        Format on save
      </text>
      <circle cx="140" cy="232" r="9" className="fill-state-conflict" />
      <text x="124" y="262" textAnchor="middle" className="fill-fg-1" fontSize="12">
        Paste and indent
      </text>
      <text x="124" y="278" textAnchor="middle" className="fill-state-conflict" fontSize="11">
        Breaks
      </text>
      {/* Decision: labels sit above the diamond so the dashed line never crosses them */}
      <path d="M430 46 L452 68 L430 90 L408 68 Z" className="fill-ink-0 stroke-node-slack" strokeWidth="1.5" strokeDasharray="3 4" />
      <text x="430" y="16" textAnchor="middle" className="fill-fg-2" fontSize="12">
        Keep comments when formatting
      </text>
      <text x="430" y="32" textAnchor="middle" className="fill-fg-3" fontSize="11">
        Decided in Slack · not in context
      </text>
      {/* Request */}
      <rect x="418" y="188" width="22" height="22" rx="3" className="fill-fg-1" />
      <text x="430" y="232" textAnchor="middle" className="fill-fg-1" fontSize="12">
        &ldquo;Make formatting faster&rdquo;
      </text>
      <text x="430" y="248" textAnchor="middle" className="fill-fg-3" fontSize="11">
        New request
      </text>
    </svg>
  )
}
