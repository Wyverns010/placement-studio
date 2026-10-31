import { useRef } from 'react'

export interface StepDef<T extends string> {
  id: T
  label: string
  /** Locked until the earlier steps have produced what this one shows. */
  enabled: boolean
}

/**
 * Numbered step bar. Each step is a native button (Tab/Enter/Space work); Left/Right/Home/End
 * move focus between unlocked steps. The current step carries aria-current="step".
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

  function onKeyDown(e: React.KeyboardEvent, i: number) {
    const open = steps.map((s, j) => (s.enabled ? j : -1)).filter((j) => j >= 0)
    const at = open.indexOf(i)
    let next = -1
    if (e.key === 'ArrowRight') next = open[Math.min(at + 1, open.length - 1)]
    else if (e.key === 'ArrowLeft') next = open[Math.max(at - 1, 0)]
    else if (e.key === 'Home') next = open[0]
    else if (e.key === 'End') next = open[open.length - 1]
    if (next == null || next < 0) return
    e.preventDefault()
    refs.current[next]?.focus()
  }

  const cur = steps.findIndex((s) => s.id === value)
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
                disabled={!s.enabled}
                onClick={() => onChange(s.id)}
                onKeyDown={(e) => onKeyDown(e, i)}
                className={`flex cursor-pointer items-center gap-2 rounded-full border px-2.5 py-1.5 text-[13px] whitespace-nowrap disabled:cursor-not-allowed sm:px-3.5 ${
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
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
