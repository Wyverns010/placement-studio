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
  const [rebuildError, setRebuildError] = useState<string | null>(null)
  const lastInput = useRef({ text: '', budget: DEFAULT_BUDGET })

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
      setError(null)
      setRebuildError(null)
      lastInput.current = { text: t, budget: b }
      setState((s) => ({ ...s, running: true }))
      try {
        const result = await runCampaign({ text: t, budget_usd: b })
        setLastResult(result)
        setState({ view: 'results', result, running: false, partial: {} })
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Something went wrong. Please try again.')
        setState((s) => ({ ...s, running: false }))
      }
    },
    [],
  )

  const rebuild = useCallback(async (answers: Record<string, string>) => {
    const { text: t, budget: b } = lastInput.current
    setRebuildError(null)
    setState((s) => ({ ...s, running: true }))
    try {
      const result = await runCampaign({ text: t, budget_usd: b, answers })
      setLastResult(result)
      setState({ view: 'results', result, running: false, partial: {} })
    } catch (e) {
      setRebuildError(e instanceof Error ? e.message : 'Something went wrong. Please try again.')
      setState((s) => ({ ...s, running: false }))
    }
  }, [])

  const pickSample = (s: Sample) => {
    edited.current = true
    setText(s.text)
    run(s.text, budget)
  }

  const goHome = () => setState((s) => ({ ...s, view: 'landing' }))

  return (
    <div className="mx-auto w-full max-w-[1180px] px-5 sm:px-7">
      <Nav onHome={goHome} />
      {state.view === 'results' && state.result ? (
        <Results
          result={state.result}
          onBack={() => {
            setRebuildError(null)
            goHome()
          }}
          samples={samples}
          onPickSample={pickSample}
          onRebuild={rebuild}
          rebuilding={state.running}
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
