import { useId, useRef } from 'react'

export interface TabDef<T extends string> {
  id: T
  label: string
  count?: number
}

/** Accessible tab bar + panel: roving tabindex, Left/Right/Home/End keys, aria linkage. */
export default function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
  variant = 'bar',
  children,
}: {
  tabs: TabDef<T>[]
  value: T
  onChange: (id: T) => void
  label: string
  variant?: 'bar' | 'segmented'
  children: React.ReactNode
}) {
  const base = useId()
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})
  const tabId = (id: string) => `${base}-tab-${id}`
  const panelId = (id: string) => `${base}-panel-${id}`

  function onKeyDown(e: React.KeyboardEvent) {
    const i = tabs.findIndex((t) => t.id === value)
    let next = -1
    if (e.key === 'ArrowRight') next = (i + 1) % tabs.length
    else if (e.key === 'ArrowLeft') next = (i - 1 + tabs.length) % tabs.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = tabs.length - 1
    if (next < 0) return
    e.preventDefault()
    onChange(tabs[next].id)
    refs.current[tabs[next].id]?.focus()
  }

  const seg = variant === 'segmented'
  return (
    <>
      <div
        role="tablist"
        aria-label={label}
        onKeyDown={onKeyDown}
        className={
          seg
            ? 'mb-3.5 inline-flex rounded-full border border-line bg-white p-[3px]'
            : 'mb-[22px] flex gap-1.5 overflow-x-auto border-b border-line'
        }
      >
        {tabs.map((t) => {
          const on = t.id === value
          return (
            <button
              key={t.id}
              ref={(el) => {
                refs.current[t.id] = el
              }}
              id={tabId(t.id)}
              type="button"
              role="tab"
              aria-selected={on}
              aria-controls={panelId(t.id)}
              tabIndex={on ? 0 : -1}
              onClick={() => onChange(t.id)}
              className={
                seg
                  ? `cursor-pointer rounded-full border-0 px-4 py-1.5 text-[13px] font-semibold ${
                      on ? 'bg-violet text-white' : 'bg-transparent text-muted'
                    }`
                  : `-mb-px cursor-pointer whitespace-nowrap border-0 border-b-2 bg-transparent px-4 py-3 text-sm ${
                      on ? 'border-violet font-semibold text-ink' : 'border-transparent font-medium text-muted'
                    }`
              }
            >
              {t.label}
              {t.count != null && (
                <em className="ml-1.5 rounded-full bg-violet-soft px-[7px] py-0.5 text-[11.5px] font-normal not-italic text-violet-dark">
                  {t.count}
                </em>
              )}
            </button>
          )
        })}
      </div>
      <div role="tabpanel" id={panelId(value)} aria-labelledby={tabId(value)}>
        {children}
      </div>
    </>
  )
}
