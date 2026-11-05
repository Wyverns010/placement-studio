import { useEffect, useRef, useState } from 'react'
import { buildConfig, createCreatives } from '../api'
import type { CampaignConfig, CampaignResult, Creative } from '../types'
import ConfigStep from './ConfigStep'
import { NoteBox, NoteList } from './NoteBox'
import OutcomeBanner from './OutcomeBanner'
import PersonasTab from './PersonasTab'
import PublishersTab from './PublishersTab'
import Stepper, { type StepDef } from './Stepper'
import { Busy, StageError } from './ui'

type Step = 'publishers' | 'personas' | 'creatives' | 'config'
/** The steps with a step-1 note box: a note re-runs step 1 and the result opens there. */
export type NoteStep = 'publishers' | 'personas'

const FALLBACK = 'Something went wrong. Please try again.'

const messageOf = (err: unknown): string => (err instanceof Error && err.message ? err.message : FALLBACK)

const isAbort = (err: unknown) => err instanceof Error && err.name === 'AbortError'

/**
 * Proceed / weak_fit results as steps: publishers → personas → ads → campaign config (budget
 * editable). Ads and config are requested from here, sending step 1's result back as it is, with
 * the step's note. Mounted fresh per step-1 result (keyed by App).
 */
export default function StagedResults({
  result,
  onNote,
  initialNote = '',
  initialStep = 'publishers',
  running = false,
}: {
  result: CampaignResult
  /** Re-runs step 1 with a note (App owns it; omit to hide the step-1 box). */
  onNote?: (note: string, from?: NoteStep) => void
  /** The note this step-1 result was produced with. */
  initialNote?: string
  /** The step that note was written on: the result opens there. */
  initialStep?: NoteStep
  running?: boolean
}) {
  const [step, setStep] = useState<Step>(initialStep)
  // Personas come after publishers: the step opens once the publishers are accepted.
  const [personasOpen, setPersonasOpen] = useState(initialStep === 'personas')
  const [noteP, setNoteP] = useState('')
  const [creatives, setCreatives] = useState<Creative[] | null>(null)
  const [config, setConfig] = useState<CampaignConfig | null>(null)
  const [pending, setPending] = useState<'creatives' | 'config' | null>(null)
  const [stepError, setStepError] = useState<string | null>(null)
  const [configBusy, setConfigBusy] = useState(false)
  const [configError, setConfigError] = useState<string | null>(null)
  // Set on Approve when some ads still carry check flags: approval goes ahead, but says so.
  const [approveWarning, setApproveWarning] = useState<string | null>(null)
  // Note boxes, and what the config note changed. Mounted fresh per step-1 result, so a new
  // campaign (or a step-1 re-run) starts with empty ones for the later steps.
  const [note1, setNote1] = useState(initialNote)
  const [note3, setNote3] = useState('')
  const [note4, setNote4] = useState('')
  const [configNotes, setConfigNotes] = useState<string[]>([])
  // The budget the config is built at: the landing value at first, then whatever the user last applied.
  const [budgetChoice, setBudgetChoice] = useState<number | null>(result.budget_usd ?? null)

  // Abort whatever is in flight when this result goes away (new run, back home, unmount).
  const inflight = useRef(new Set<AbortController>())
  useEffect(() => {
    const set = inflight.current
    return () => set.forEach((c) => c.abort())
  }, [])
  const track = () => {
    const c = new AbortController()
    inflight.current.add(c)
    return { signal: c.signal, abort: () => c.abort(), done: () => inflight.current.delete(c) }
  }

  // Move focus to the step heading on step changes (not on first render).
  const heading = useRef<HTMLHeadingElement>(null)
  const firstRender = useRef(true)
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false
      return
    }
    heading.current?.focus()
  }, [step])


  /**
   * One config request at a time. Starting a new one, rewriting the ads, or leaving step 3 aborts the
   * current one and bumps the version, so a late response can't re-set a config that was cleared
   * or replaced.
   */
  const configReq = useRef<{ ver: number; abort: (() => void) | null }>({ ver: 0, abort: null })
  const cancelConfig = () => {
    configReq.current.abort?.()
    configReq.current = { ver: configReq.current.ver + 1, abort: null }
    setConfigBusy(false)
    setPending((p) => (p === 'config' ? null : p))
  }
  const startConfig = () => {
    cancelConfig()
    const t = track()
    const ver = configReq.current.ver
    configReq.current.abort = t.abort
    return { ...t, current: () => configReq.current.ver === ver }
  }

  const goTo = (s: Step) => {
    setStepError(null)
    if (s !== step && step === 'config') cancelConfig()
    setStep(s)
  }

  /** Requests the ads; with a note it re-writes them and drops any config built from the old ones. */
  async function writeAds(note = '') {
    if (creatives && !note) return goTo('creatives')
    const t = track()
    setPending('creatives')
    setStepError(null)
    try {
      const out = await createCreatives(result, note, t.signal)
      if (note) {
        cancelConfig()
        setConfig(null)
        setConfigError(null)
        setApproveWarning(null)
        setConfigNotes([])
      }
      setCreatives(out)
      setStep('creatives')
    } catch (err) {
      if (!isAbort(err)) setStepError(messageOf(err))
    } finally {
      t.done()
      if (!t.signal.aborted) setPending(null)
    }
  }

  async function approve() {
    if (!creatives) return
    if (config) return goTo('config')
    const t = startConfig()
    setPending('config')
    setStepError(null)
    try {
      setConfigNotes([])
      const out = await buildConfig(result, creatives, budgetChoice, '', t.signal)
      if (!t.current()) return
      setConfig(out.config)
      setApproveWarning(flagWarning(creatives, result.personas))
      setConfigError(null)
      setStep('config')
    } catch (err) {
      if (t.current() && !isAbort(err)) setStepError(messageOf(err))
    } finally {
      t.done()
      if (t.current()) setPending(null)
    }
  }

  /** Re-requests the config at `budget` (null = the recommendation). Keeps the old config on failure. */
  async function updateBudget(budget: number | null, note = '') {
    if (!creatives) return
    const t = startConfig()
    setConfigBusy(true)
    setConfigError(null)
    try {
      const out = await buildConfig(result, creatives, budget, note, t.signal)
      if (!t.current()) return
      setConfig(out.config)
      setConfigNotes(note ? out.notes : [])
      // A budget change rebuilds without the note, so the box empties to match what's shown.
      if (!note) setNote4('')
      // an amount in the note replaces the field (it's the newer instruction): keep it for later updates
      setBudgetChoice(note && out.config.budget.source === 'user' ? out.config.budget.monthly_usd : budget)
    } catch (err) {
      if (t.current() && !isAbort(err)) setConfigError(messageOf(err))
    } finally {
      t.done()
      if (t.current()) setConfigBusy(false)
    }
  }

  const recCount = result.publishers.filter((p) => p.recommended).length
  const steps: StepDef<Step>[] = [
    { id: 'publishers', label: 'Publishers', enabled: true },
    { id: 'personas', label: 'Personas', enabled: personasOpen, hint: 'Accept the publishers first.' },
    { id: 'creatives', label: 'Creatives', enabled: !!creatives, hint: 'Write the ads first.' },
    { id: 'config', label: 'Campaign config', enabled: !!config, hint: 'Approve creatives first.' },
  ]
  /** A personas note keeps the publishers note it was built on (both are step-1 notes). */
  const personasNote = (text: string) => [initialNote.trim(), text.trim()].filter(Boolean).join('. ')

  const headingCls = 'm-0 text-lg font-semibold tracking-[-0.01em] outline-none sm:text-xl'
  const errorBlock = stepError && (
    <div className="mt-4">
      <StageError message={stepError} />
    </div>
  )

  return (
    <div className="pb-20">
      {result.outcome === 'weak_fit' && (
        <div className="mb-4">
          <OutcomeBanner
            variant="amber"
            title={recCount === 0 ? 'No publisher fits.' : 'Weak fit — treat this as a test.'}
          >
            {result.message && <p className="m-0">{result.message}</p>}
          </OutcomeBanner>
        </div>
      )}

      <Stepper steps={steps} value={step} onChange={goTo} />

      {step === 'publishers' && (
        <section aria-labelledby="step-publishers">
          <StepHead
            id="step-publishers"
            headingRef={heading}
            className={headingCls}
            title={`${recCount} publisher${recCount === 1 ? '' : 's'}`}
            sub="Where your ads will run. The personas are picked next, for these publishers."
            actions={
              <>
                <button
                  type="button"
                  className="pill pill-primary"
                  disabled={recCount === 0}
                  onClick={() => {
                    setPersonasOpen(true)
                    goTo('personas')
                  }}
                >
                  Pick personas for these publishers →
                </button>
              </>
            }
          />
          {onNote && (
            <NoteBox
              placeholder="Skip Pawline"
              value={note1}
              onChange={setNote1}
              onApply={(t) => onNote(t, 'publishers')}
              busy={running}
              allowBlank={!!initialNote}
            />
          )}
          <NoteList className="mb-5" notes={initialNote && initialStep === 'publishers' ? result.notes : undefined} />
          <PublishersTab publishers={result.publishers} config={config} />
        </section>
      )}

      {step === 'personas' && (
        <section aria-labelledby="step-personas">
          <StepHead
            id="step-personas"
            headingRef={heading}
            className={headingCls}
            title={`${result.personas.length} persona${result.personas.length === 1 ? '' : 's'}`}
            sub="Who the ads are written for: scored on the brief and on the publishers you kept (what they sell and who shops there)."
            actions={
              <>
                <button type="button" className="pill" onClick={() => goTo('publishers')}>
                  ← Back to publishers
                </button>
                <button
                  type="button"
                  className="pill pill-primary"
                  disabled={pending === 'creatives' || recCount === 0 || result.personas.length === 0}
                  onClick={() => writeAds()}
                >
                  {pending === 'creatives' ? <Busy label="Writing ads…" /> : 'Write ads for these personas →'}
                </button>
              </>
            }
          />
          {onNote && (
            <NoteBox
              placeholder="Drop the Gifter"
              value={noteP}
              onChange={setNoteP}
              onApply={(t) => onNote(personasNote(t), 'personas')}
              busy={running}
            />
          )}
          <NoteList className="mb-5" notes={initialNote && initialStep === 'personas' ? result.notes : undefined} />
          <PersonasTab personas={result.personas} publishers={result.publishers} />
          {errorBlock}
        </section>
      )}

      {step === 'creatives' && creatives && (
        <section aria-labelledby="step-creatives">
          <StepHead
            id="step-creatives"
            headingRef={heading}
            className={headingCls}
            title="Review the ads"
            sub="One ad per persona, each written for one publisher; publishers without their own ad reuse one (the config says which). Add a note to rewrite them."
            actions={
              <>
                <button type="button" className="pill" onClick={() => goTo('personas')}>
                  ← Back to personas
                </button>
                <button
                  type="button"
                  className="pill pill-primary"
                  disabled={pending === 'config'}
                  onClick={approve}
                >
                  {pending === 'config' ? <Busy label="Building config…" /> : 'Approve creatives & build config →'}
                </button>
              </>
            }
          />
          <NoteBox
            placeholder="Make them more playful"
            value={note3}
            onChange={setNote3}
            onApply={(t) => writeAds(t)}
            busy={pending === 'creatives'}
            disabled={pending === 'config'}
          />
          {errorBlock}
          <PersonasTab personas={result.personas} creatives={creatives} publishers={result.publishers} />
        </section>
      )}

      {step === 'config' && config && (
        <section aria-labelledby="step-config">
          <StepHead
            id="step-config"
            headingRef={heading}
            className={headingCls}
            title="Campaign config"
            sub="Launch-ready settings. Change the budget and the split, pacing and caps follow."
            actions={
              <>
                <button type="button" className="pill" onClick={() => goTo('creatives')}>
                  ← Back to creatives
                </button>
              </>
            }
          />
          {approveWarning && (
            <p data-testid="approve-warning" role="status" className="m-0 mb-4 rounded-lg border border-[#F0D9B2] bg-[#FBEFDC] px-3 py-2 text-[13px] text-[#5B4520]">
              {approveWarning}
            </p>
          )}
          <NoteBox
            placeholder="Keep it under $5,000"
            value={note4}
            onChange={setNote4}
            onApply={(t) => updateBudget(budgetChoice, t)}
            busy={configBusy}
          />
          <NoteList className="mb-5" notes={configNotes} />
          <ConfigStep
            config={config}
            publishers={result.publishers}
            personas={result.personas}
            creatives={creatives ?? []}
            busy={configBusy}
            error={configError}
            onBudget={updateBudget}
          />
        </section>
      )}
    </div>
  )
}

/** One line naming each approved ad that still has check flags, or null when none do. */
function flagWarning(creatives: Creative[], personas: CampaignResult['personas']): string | null {
  const name = (id: string) => personas.find((p) => p.persona_id === id)?.name ?? id
  const flagged = creatives.filter((c) => c.fact_violations.length > 0)
  if (flagged.length === 0) return null
  return (
    'Approved with unresolved checks — ' +
    flagged.map((c) => `${name(c.persona_id)}: ${c.fact_violations.join('; ')}`).join(' · ')
  )
}

function StepHead({
  id,
  title,
  sub,
  className,
  headingRef,
  actions,
}: {
  id: string
  title: string
  sub: string
  className: string
  headingRef: React.Ref<HTMLHeadingElement>
  /** The step's back / next buttons, at the top so they're in view without scrolling. */
  actions?: React.ReactNode
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div className="min-w-0 flex-1 basis-[320px]">
        <h3 id={id} ref={headingRef} tabIndex={-1} className={className}>
          {title}
        </h3>
        <p className="m-0 mt-1 text-[13.5px] text-muted">{sub}</p>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-3">{actions}</div>}
    </div>
  )
}

