import { useId, useState } from 'react'
import { STEER_MAX, type AgentMode, type AgentTraceEntry, type StepMeta } from '../types'
import { Busy } from './ui'

const MODE_LABEL: Record<AgentMode, string> = {
  agent: 'Agent',
  code: 'Code',
  cached: 'Cached',
  fallback: 'Fallback (agent unavailable)',
}

const MODE_CLS: Record<AgentMode, string> = {
  agent: 'bg-violet-soft text-violet-dark',
  code: 'bg-[#eceaf2] text-muted',
  cached: 'bg-[#eceaf2] text-muted',
  fallback: 'bg-[#FBEFDC] text-[#5B4520]',
}

export function ModeBadge({ mode }: { mode: AgentMode }) {
  return (
    <span
      data-testid="mode-badge"
      className={`rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold ${MODE_CLS[mode] ?? MODE_CLS.code}`}
    >
      {MODE_LABEL[mode] ?? mode}
    </span>
  )
}

/** "Agent: <tool> …" — the latest tool call while stage 1 streams in. */
export function AgentTicker({ trace }: { trace?: AgentTraceEntry[] }) {
  const last = trace?.at(-1)
  if (!last) return null
  return (
    <p data-testid="agent-ticker" role="status" className="m-0 mb-2.5 truncate text-[12px] text-muted">
      Agent: <span className="font-mono text-violet-dark">{last.tool}</span> …
    </p>
  )
}

/** Collapsed-by-default "What the agent did": notes first, then the tool-call timeline. */
export function AgentPanel({ meta, className = '' }: { meta?: StepMeta; className?: string }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const trace = meta?.agent_trace ?? []
  const notes = meta?.agent_notes ?? []
  if (!meta || (!meta.mode && !trace.length && !notes.length)) return null
  return (
    <section aria-label="Agent activity" className={`rounded-xl border border-line bg-white ${className}`}>
      <div className="flex flex-wrap items-center gap-2.5 px-3.5 py-2.5">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen((o) => !o)}
          className="cursor-pointer border-0 bg-transparent p-0 text-[13px] font-semibold text-ink"
        >
          <span aria-hidden="true" className="mr-1.5 inline-block w-3 text-muted">
            {open ? '▾' : '▸'}
          </span>
          What the agent did
        </button>
        {meta.mode && <ModeBadge mode={meta.mode} />}
      </div>
      {open && (
        <div id={id} className="border-t border-line px-3.5 py-3 text-[13px]">
          {notes.length > 0 && (
            <ul data-testid="agent-notes" className="m-0 mb-3 list-disc space-y-1 pl-5 leading-snug">
              {notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
          {trace.length > 0 ? (
            <ol data-testid="agent-timeline" className="m-0 list-none space-y-2 p-0">
              {trace.map((t, i) => (
                <li key={i} className="grid grid-cols-[1fr_auto] gap-x-3 border-l-2 border-[#d9cff0] pl-3">
                  <span className="text-[12.5px]">
                    <b>{t.agent}</b> <span className="text-muted">→</span>{' '}
                    <span className="font-mono text-violet-dark">{t.tool}</span>
                  </span>
                  <span className="text-[11.5px] text-muted">{t.ms != null ? `${t.ms} ms` : ''}</span>
                  {t.args_summary && t.args_summary !== '{}' && (
                    <span className="col-span-2 truncate font-mono text-[11.5px] text-muted" title={t.args_summary}>
                      {t.args_summary}
                    </span>
                  )}
                  {t.result_summary && (
                    <span className="col-span-2 truncate text-[12px] text-muted" title={t.result_summary}>
                      {t.result_summary}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <p className="m-0 text-muted">No tool calls were made.</p>
          )}
        </div>
      )}
    </section>
  )
}

/** Compact "Tell the agent…" box (≤ 300 chars, counter) with an Apply button. */
export function AgentSteer({
  placeholder,
  value,
  onChange,
  onApply,
  busy = false,
  disabled = false,
  allowBlank = false,
}: {
  placeholder: string
  value: string
  onChange: (v: string) => void
  onApply: (steer: string) => void
  busy?: boolean
  disabled?: boolean
  /** Blank Apply is allowed (clears a steer that was applied earlier). */
  allowBlank?: boolean
}) {
  const trimmed = value.trim()
  const canApply = !busy && !disabled && trimmed.length <= STEER_MAX && (trimmed.length > 0 || allowBlank)
  return (
    <form
      className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-line bg-white px-3 py-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (canApply) onApply(trimmed)
      }}
    >
      <input
        aria-label="Tell the agent"
        placeholder={`Tell the agent… e.g. ${placeholder}`}
        value={value}
        maxLength={STEER_MAX}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-[180px] flex-1 border-0 bg-transparent font-[inherit] text-[13.5px] outline-none"
      />
      <span className="text-[11.5px] text-muted" aria-live="off" data-testid="steer-count">
        {value.length}/{STEER_MAX}
      </span>
      <button type="submit" className="pill pill-sm" disabled={!canApply}>
        {busy ? <Busy label="Applying…" /> : 'Apply'}
      </button>
    </form>
  )
}
