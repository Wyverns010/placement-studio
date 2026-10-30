import { useCallback, useEffect, useRef, useState } from 'react'
import { getSamples, runCampaign } from './api'
import Landing from './components/Landing'
import Nav from './components/Nav'
import Results from './components/Results'
import type { CampaignResult, Sample } from './types'

const DEFAULT_BUDGET = 25000

export interface AppState {
  view: 'landing' | 'results'
  result?: CampaignResult
  running: boolean
  partial: Partial<CampaignResult>
}

export default function App() {
  const [state, setState] = useState<AppState>({ view: 'landing', running: false, partial: {} })
  const [samples, setSamples] = useState<Sample[]>([])
  const [text, setText] = useState('')
  const [budget, setBudget] = useState(DEFAULT_BUDGET)
  const [error, setError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<CampaignResult | null>(null)
  const edited = useRef(false)
  const token = useRef(0)
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

  const run = useCallback(
    async (t: string, b: number) => {
      const my = ++token.current
      const fromResults = viewRef.current === 'results'
      setError(null)
      setRebuildError(null)
      setState((s) => ({ ...s, running: true }))
      try {
        const result = await runCampaign({ text: t, budget_usd: b })
        if (my !== token.current) return
        lastInput.current = { text: t, budget: b, answers: {} }
        setLastResult(result)
        setState({ view: 'results', result, running: false, partial: {} })
      } catch (e) {
        if (my !== token.current) return
        const msg = e instanceof Error ? e.message : 'Something went wrong. Please try again.'
        // On the results view, failures show in the red results banner, not the hidden landing form.
        if (fromResults) setRebuildError(msg)
        else setError(msg)
        setState((s) => ({ ...s, running: false }))
      }
    },
    [],
  )

  const rebuild = useCallback(async (answers: Record<string, string>) => {
    const { text: t, budget: b, answers: prior } = lastInput.current
    // Keep earlier answers (the backend caps at 5; drop the oldest first).
    const next = { ...prior }
    for (const [q, a] of Object.entries(answers)) {
      delete next[q] // re-add so a re-answered question counts as newest
      next[q] = a
    }
    const merged = Object.fromEntries(Object.entries(next).slice(-5))
    const my = ++token.current
    setRebuildError(null)
    setState((s) => ({ ...s, running: true }))
    try {
      const raw = await runCampaign({ text: t, budget_usd: b, answers: merged })
      if (my !== token.current) return
      lastInput.current = { text: t, budget: b, answers: merged }
      // The API echoes the text with answers appended; show what the user typed.
      const result = { ...raw, input_text: t }
      setLastResult(result)
      setState({ view: 'results', result, running: false, partial: {} })
    } catch (e) {
      if (my !== token.current) return
      setRebuildError(e instanceof Error ? e.message : 'Something went wrong. Please try again.')
      setState((s) => ({ ...s, running: false }))
    }
  }, [])

  const pickSample = (s: Sample) => {
    edited.current = true
    setText(s.text)
    run(s.text, budget)
  }

  viewRef.current = state.view

  const goHome = () => {
    token.current++ // ignore any in-flight request
    setRebuildError(null)
    setState((s) => ({ ...s, view: 'landing', running: false }))
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
