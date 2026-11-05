import { useCallback, useEffect, useRef, useState } from 'react'
import { getSamples, runCampaign } from './api'
import { parseBudgetInput } from './format'
import Landing from './components/Landing'
import Nav from './components/Nav'
import Results from './components/Results'
import type { NoteStep } from './components/StagedResults'
import type { Brief, CampaignRequest, CampaignResult, Sample } from './types'

export interface AppState {
  view: 'landing' | 'results'
  result?: CampaignResult
  /** What the user typed (the API echoes the text with clarify answers appended). */
  displayText?: string
  /** Bumped per shown result so the staged results start fresh at step 1. */
  runId: number
  running: boolean
}

/** The typed budget, or null when blank or invalid (Landing blocks running with an invalid one). */
function budgetValue(raw: string): number | null {
  const p = parseBudgetInput(raw)
  return p.ok ? p.value : null
}

/** What step 1 was last run with. `brief` is the reading without a note, sent back with a note. */
interface LastInput {
  text: string
  budget: number | null
  answers: Record<string, string>
  note: string
  brief: Brief | null
}

export default function App() {
  const [state, setState] = useState<AppState>({ view: 'landing', runId: 0, running: false })
  const [samples, setSamples] = useState<Sample[]>([])
  const [text, setText] = useState('')
  const [budget, setBudget] = useState('') // raw text; blank = use the recommendation
  const [error, setError] = useState<string | null>(null)
  const [rebuildError, setRebuildError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<CampaignResult | null>(null)
  const [note, setNote] = useState('')
  const [noteFrom, setNoteFrom] = useState<NoteStep>('publishers') // the step the shown result's note was written on
  const edited = useRef(false)
  const token = useRef(0)
  const inflight = useRef<AbortController | null>(null)
  const lastInput = useRef<LastInput>({ text: '', budget: null, answers: {}, note: '', brief: null })

  useEffect(() => {
    let alive = true
    getSamples()
      .then((s) => {
        if (!alive) return
        setSamples(s)
        if (s.length && !edited.current) setText(s[0].text)
      })
      .catch(() => {
        /* the sample buttons are optional; the text box still works */
      })
    return () => {
      alive = false
    }
  }, [])

  const stop = useCallback(() => {
    inflight.current?.abort()
    inflight.current = null
  }, [])

  useEffect(() => stop, [stop])

  /** Runs step 1 once; a newer run (or going home) cancels this one. */
  const runStep1 = useCallback(
    (req: CampaignRequest, onDone: (r: CampaignResult) => void, onFail: (msg: string) => void) => {
      stop()
      const my = ++token.current
      const ctl = (inflight.current = new AbortController())
      setRebuildError(null)
      setState((s) => ({ ...s, running: true }))
      runCampaign(req, ctl.signal)
        .then((result) => {
          if (my === token.current) onDone(result)
        })
        .catch((err: unknown) => {
          if (my !== token.current || ctl.signal.aborted) return
          setState((s) => ({ ...s, running: false }))
          onFail(err instanceof Error && err.message ? err.message : 'Something went wrong. Please try again.')
        })
    },
    [stop],
  )

  const show = (result: CampaignResult, displayText: string) =>
    setState((s) => ({ view: 'results', result, displayText, runId: s.runId + 1, running: false }))

  const run = useCallback(
    (t: string, b: number | null) => {
      const fromResults = state.view === 'results'
      setError(null)
      runStep1(
        b != null ? { text: t, budget_usd: b } : { text: t },
        (result) => {
          // A new campaign starts without the previous campaign's note.
          lastInput.current = { text: t, budget: b, answers: {}, note: '', brief: result.brief }
          setNote('')
          setLastResult(result)
          show(result, t)
        },
        // On the results view, failures show in the results banner, not the hidden landing form.
        (msg) => (fromResults ? setRebuildError(msg) : setError(msg)),
      )
    },
    [runStep1, state.view],
  )

  /** Re-runs step 1 with clarify answers (the text is read again) or a note (the brief is reused). */
  const rebuild = useCallback(
    (answers: Record<string, string>, newNote?: string) => {
      const { text: t, budget: b, answers: prior, brief } = lastInput.current
      const nextNote = newNote ?? lastInput.current.note
      const merged = { ...prior, ...answers }
      const reuse = Object.keys(answers).length === 0 && nextNote && brief
      const req: CampaignRequest = {
        text: t,
        answers: merged,
        ...(b != null ? { budget_usd: b } : {}),
        ...(nextNote ? { note: nextNote } : {}),
        ...(reuse ? { brief } : {}),
      }
      runStep1(
        req,
        (result) => {
          // Answers change the reading, so its brief becomes the one a later note reuses.
          const base = reuse ? brief : result.brief
          lastInput.current = { text: t, budget: b, answers: merged, note: nextNote, brief: base }
          setNote(nextNote)
          // The API echoes the text with answers appended: keep it (steps 3 and 4 need it unchanged)
          // and show what the user typed.
          setLastResult({ ...result, input_text: t })
          show(result, t)
        },
        setRebuildError,
      )
    },
    [runStep1],
  )

  const pickSample = (s: Sample) => {
    edited.current = true
    setText(s.text)
    run(s.text, budgetValue(budget))
  }

  const goHome = () => {
    token.current++ // ignore any in-flight request
    stop()
    setRebuildError(null)
    setState((s) => ({ ...s, view: 'landing', running: false }))
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
          onNote={(n, from = 'publishers') => {
            setNoteFrom(from)
            rebuild({}, n)
          }}
          note={note}
          noteFrom={noteFrom}
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
          onRun={() => run(text, budgetValue(budget))}
          onPickSample={pickSample}
        />
      )}
    </div>
  )
}
