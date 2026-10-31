import { useCallback, useEffect, useRef, useState } from 'react'
import { getSamples, streamCampaign } from './api'
import { parseBudgetInput } from './format'
import Landing from './components/Landing'
import Nav from './components/Nav'
import Results from './components/Results'
import type { CampaignRequest, CampaignResult, Sample, StageEvent, StreamPartial } from './types'

export interface AppState {
  view: 'landing' | 'results'
  result?: CampaignResult
  /** What the user typed (the API echoes the text with clarify answers appended). */
  displayText?: string
  /** Bumped per shown result so the staged results start fresh at step 1. */
  runId: number
  running: boolean
  partial: StreamPartial
}

const HOLD_MS = 600
const reducedMotion = () =>
  typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** Sends budget_usd only when the user typed one; otherwise the backend recommends it. */
function withBudget(req: CampaignRequest, b: number | null): CampaignRequest {
  return b != null ? { ...req, budget_usd: b } : req
}

/** The typed budget, or null when blank or invalid (Landing blocks running with an invalid one). */
function budgetValue(raw: string): number | null {
  const p = parseBudgetInput(raw)
  return p.ok ? p.value : null
}

export default function App() {
  const [state, setState] = useState<AppState>({ view: 'landing', runId: 0, running: false, partial: {} })
  const [samples, setSamples] = useState<Sample[]>([])
  const [text, setText] = useState('')
  const [budget, setBudget] = useState('') // raw text; blank = use the recommendation
  const [error, setError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<CampaignResult | null>(null)
  const edited = useRef(false)
  const token = useRef(0)
  const cancelStream = useRef<(() => void) | null>(null)
  const holdTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const viewRef = useRef<AppState['view']>('landing')
  const [rebuildError, setRebuildError] = useState<string | null>(null)
  const lastInput = useRef<{ text: string; budget: number | null; answers: Record<string, string> }>({
    text: '',
    budget: null,
    answers: {},
  })

  useEffect(() => {
    let alive = true
    getSamples()
      .then((s) => {
        if (!alive) return
        setSamples(s)
        if (s.length && !edited.current) setText(s[0].text)
      })
      .catch(() => {
        /* chips are optional; the textarea still works */
      })
    return () => {
      alive = false
    }
  }, [])

  const stop = useCallback(() => {
    cancelStream.current?.()
    cancelStream.current = null
    clearTimeout(holdTimer.current)
  }, [])

  useEffect(() => stop, [stop])

  /**
   * Streams one run and marks the app as running. `onDone` receives the full result and this
   * run's token; `onFail` the message (running is already cleared). Starting a new stream (or
   * going home) cancels the previous one.
   */
  const startStream = useCallback(
    (req: CampaignRequest, onDone: (r: CampaignResult, my: number) => void, onFail: (msg: string) => void) => {
      stop()
      const my = ++token.current
      setRebuildError(null)
      setState((s) => ({ ...s, running: true, partial: {} }))
      cancelStream.current = streamCampaign(req, (e: StageEvent) => {
        if (my !== token.current) return
        if (e.stage === 'error') {
          cancelStream.current = null
          const d = e.data as { message?: string; detail?: string }
          setState((s) => ({ ...s, running: false, partial: {} }))
          onFail(d.message ?? d.detail ?? 'Something went wrong. Please try again.')
        } else if (e.stage === 'done') {
          cancelStream.current = null
          onDone(e.data as unknown as CampaignResult, my)
        } else {
          setState((s) => ({ ...s, partial: { ...s.partial, [e.stage]: e.data } as StreamPartial }))
        }
      })
    },
    [stop],
  )

  const run = useCallback(
    (t: string, b: number | null) => {
      const fromResults = viewRef.current === 'results'
      setError(null)
      startStream(
        withBudget({ text: t }, b),
        (result, my) => {
          lastInput.current = { text: t, budget: b, answers: {} }
          setLastResult(result)
          const show = () =>
            setState((s) => ({ view: 'results', result, displayText: t, runId: s.runId + 1, running: false, partial: {} }))
          if (fromResults || reducedMotion()) return show()
          // Keep the filled panel on screen briefly so the last lane is seen.
          setState((s) => ({ ...s, partial: { ...s.partial, done: true } }))
          holdTimer.current = setTimeout(() => {
            if (my === token.current) show()
          }, HOLD_MS)
        },
        (msg) => {
          // On the results view, failures show in the red results banner, not the hidden landing form.
          if (fromResults) setRebuildError(msg)
          else setError(msg)
        },
      )
    },
    [startStream],
  )

  const rebuild = useCallback(
    (answers: Record<string, string>) => {
      const { text: t, budget: b, answers: prior } = lastInput.current
      // Keep earlier answers (the backend caps at 5; drop the oldest first).
      const next = { ...prior }
      for (const [q, a] of Object.entries(answers)) {
        delete next[q] // re-add so a re-answered question counts as newest
        next[q] = a
      }
      const merged = Object.fromEntries(Object.entries(next).slice(-5))
      startStream(
        withBudget({ text: t, answers: merged }, b),
        (result) => {
          lastInput.current = { text: t, budget: b, answers: merged }
          // The API echoes the text with answers appended: keep it (stages 2 and 3 need it
          // unchanged) and show what the user typed.
          setLastResult({ ...result, input_text: t })
          setState((s) => ({ view: 'results', result, displayText: t, runId: s.runId + 1, running: false, partial: {} }))
        },
        setRebuildError,
      )
    },
    [startStream],
  )

  const pickSample = (s: Sample) => {
    edited.current = true
    setText(s.text)
    run(s.text, budgetValue(budget))
  }

  viewRef.current = state.view

  const goHome = () => {
    token.current++ // ignore any in-flight request
    stop()
    setRebuildError(null)
    setState((s) => ({ ...s, view: 'landing', running: false, partial: {} }))
  }

  return (
    <div className="mx-auto w-full max-w-[1180px] px-5 sm:px-7">
      <Nav onHome={goHome} />
      {state.view === 'results' && state.result ? (
        <Results
          key={state.runId}
          result={state.result}
          displayText={state.displayText}
          onBack={goHome}
          samples={samples}
          onPickSample={pickSample}
          onRebuild={rebuild}
          onRerun={() => rebuild({})}
          running={state.running}
          rebuildError={rebuildError}
        />
      ) : (
        <Landing
          samples={samples}
          text={text}
          budget={budget}
          running={state.running}
          error={error}
          lastResult={lastResult}
          partial={state.partial}
          onTextChange={(t) => {
            edited.current = true
            setText(t)
          }}
          onBudgetChange={setBudget}
          onRun={() => run(text, budgetValue(budget))}
          onPickSample={pickSample}
        />
      )}
    </div>
  )
}
