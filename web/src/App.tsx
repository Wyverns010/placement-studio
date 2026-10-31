import { useCallback, useEffect, useRef, useState } from 'react'
import { getSamples, streamCampaign } from './api'
import Landing from './components/Landing'
import Nav from './components/Nav'
import Results from './components/Results'
import type { CampaignRequest, CampaignResult, Sample, StageEvent, StreamPartial } from './types'

const DEFAULT_BUDGET = 25000

export interface AppState {
  view: 'landing' | 'results'
  result?: CampaignResult
  running: boolean
  partial: StreamPartial
}

const HOLD_MS = 600
const reducedMotion = () =>
  typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export default function App() {
  const [state, setState] = useState<AppState>({ view: 'landing', running: false, partial: {} })
  const [samples, setSamples] = useState<Sample[]>([])
  const [text, setText] = useState('')
  const [budget, setBudget] = useState(DEFAULT_BUDGET)
  const [error, setError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<CampaignResult | null>(null)
  const edited = useRef(false)
  const token = useRef(0)
  const cancelStream = useRef<(() => void) | null>(null)
  const holdTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const viewRef = useRef<AppState['view']>('landing')
  const [rebuildError, setRebuildError] = useState<string | null>(null)
  const lastInput = useRef<{ text: string; budget: number; answers: Record<string, string> }>({
    text: '',
    budget: DEFAULT_BUDGET,
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
    (t: string, b: number) => {
      const fromResults = viewRef.current === 'results'
      setError(null)
      startStream(
        { text: t, budget_usd: b },
        (result, my) => {
          lastInput.current = { text: t, budget: b, answers: {} }
          setLastResult(result)
          const show = () =>
            setState({ view: 'results', result, running: false, partial: {} })
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
        { text: t, budget_usd: b, answers: merged },
        (raw) => {
          lastInput.current = { text: t, budget: b, answers: merged }
          // The API echoes the text with answers appended; show what the user typed.
          const result = { ...raw, input_text: t }
          setLastResult(result)
          setState({ view: 'results', result, running: false, partial: {} })
        },
        setRebuildError,
      )
    },
    [startStream],
  )

  const pickSample = (s: Sample) => {
    edited.current = true
    setText(s.text)
    run(s.text, budget)
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
          result={state.result}
          onBack={goHome}
          samples={samples}
          onPickSample={pickSample}
          onRebuild={rebuild}
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
          onRun={() => run(text, budget)}
          onPickSample={pickSample}
        />
      )}
    </div>
  )
}
