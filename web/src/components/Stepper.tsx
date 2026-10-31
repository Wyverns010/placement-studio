import { useId, useRef, useState } from 'react'

export interface StepDef<T extends string> {
  id: T
  label: string
  /** Locked until the earlier steps have produced what this one shows. */
  enabled: boolean
  /** Why a locked step can't be opened yet, e.g. "Approve creatives first." */
  hint?: string
}

/**
 * Numbered step bar. Each step is a native button (Tab/Enter/Space work); Left/Right/Home/End
 * move focus between steps. The current step carries aria-current="step". Locked steps stay
 * focusable with aria-disabled and explain why (described-by text, shown when activated).
 */
export default function Stepper<T extends string>({
  steps,
  value,
  onChange,
}: {
  steps: StepDef<T>[]
  value: T
  onChange: (id: T) => void
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const base = useId()
  const [told, setTold] = useState<T | null>(null)

  function onKeyDown(e: React.KeyboardEvent, i: number) {
    let next = -1
    if (e.key === 'ArrowRight') next = Math.min(i + 1, steps.length - 1)
    else if (e.key === 'ArrowLeft') next = Math.max(i - 1, 0)
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = steps.length - 1
    if (next < 0) return
    e.preventDefault()
    refs.current[next]?.focus()
  }

  const cur = steps.findIndex((s) => s.id === value)
  const toldStep = steps.find((s) => s.id === told && !s.enabled)
  return (
    <nav aria-label="Campaign steps" className="mb-6">
      <ol className="m-0 flex list-none items-center gap-1.5 overflow-x-auto p-0 sm:gap-2">
        {steps.map((s, i) => {
          const on = s.id === value
          const done = i < cur
          return (
            <li key={s.id} className="flex min-w-0 shrink-0 items-center gap-1.5 sm:gap-2">
              {i > 0 && (
                <span
                  aria-hidden="true"
                  className={`h-px w-4 sm:w-10 ${i <= cur ? 'bg-violet' : 'bg-line'}`}
                />
              )}
              <button
                ref={(el) => {
                  refs.current[i] = el
                }}
                type="button"
                aria-current={on ? 'step' : undefined}
                aria-disabled={!s.enabled || undefined}
                aria-describedby={!s.enabled && s.hint ? `${base}-hint-${i}` : undefined}
                title={!s.enabled ? s.hint : undefined}
                onClick={() => {
                  if (s.enabled) {
                    setTold(null)
                    onChange(s.id)
                  } else setTold(s.id)
                }}
                onKeyDown={(e) => onKeyDown(e, i)}
                className={`flex cursor-pointer items-center gap-2 rounded-full border px-2.5 py-1.5 text-[13px] whitespace-nowrap aria-disabled:cursor-not-allowed sm:px-3.5 ${
                  on
                    ? 'border-violet bg-violet-soft font-semibold text-violet-dark'
                    : s.enabled
                      ? 'border-line bg-white font-medium text-ink hover:border-violet'
                      : 'border-dashed border-line bg-transparent font-medium text-muted'
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`grid h-[22px] w-[22px] place-items-center rounded-full text-[11.5px] font-bold ${
                    on ? 'bg-violet text-white' : done ? 'bg-violet-soft text-violet-dark' : 'bg-[#eee9f6] text-muted'
                  }`}
                >
                  {done && !on ? '✓' : i + 1}
                </span>
                <span className="sr-only">Step {i + 1}: </span>
                {/* On phones only the current step shows its label; the others stay readable to AT. */}
                <span className={on ? '' : 'max-sm:sr-only'}>{s.label}</span>
              </button>
              {!s.enabled && s.hint && (
                <span id={`${base}-hint-${i}`} className="sr-only">
                  {s.hint}
                </span>
              )}
            </li>
          )
        })}
      </ol>
      <p role="status" className="m-0 mt-2 min-h-0 text-[12.5px] text-muted empty:hidden">
        {toldStep?.hint ?? ''}
      </p>
    </nav>
  )
}
