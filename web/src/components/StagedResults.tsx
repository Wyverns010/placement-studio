import { useEffect, useRef, useState } from 'react'
import { ApiError, buildConfig, createCreatives, regenerateCreative } from '../api'
import { usd } from '../format'
import { STEER_MAX, type CampaignConfig, type CampaignResult, type Creative, type StagePayload, type StepMeta } from '../types'
import { AgentNotes, AgentSteer, AgentWorking } from './AgentUi'
import ConfigStep from './ConfigStep'
import OutcomeBanner from './OutcomeBanner'
import PersonasTab from './PersonasTab'
import PublishersTab from './PublishersTab'
import RegenerateControls from './RegenerateControls'
import Stepper, { type StepDef } from './Stepper'
import { Busy, StageError, type StageErr } from './ui'

type Step = 'publishers' | 'personas' | 'creatives' | 'config'
/** The steps with a stage-1 steer box: a steer re-runs stage 1 and the result opens there. */
export type SteerStep = 'publishers' | 'personas'

const FALLBACK = 'Something went wrong. Please try again.'

/** ApiError → inline error; a 403 means the stage-1 result changed or expired (re-run it). */
function toStageErr(err: unknown): StageErr {
  const message = err instanceof Error && err.message ? err.message : FALLBACK
  return { message, expired: err instanceof ApiError && err.status === 403 }
}

const isAbort = (err: unknown) => err instanceof Error && err.name === 'AbortError'

/**
 * Proceed / weak_fit results as three steps: ① publishers & personas → ② creatives (per-ad
 * Regenerate) → ③ campaign config (budget editable). Stages 2 and 3 are requested from here,
 * sending stage 1's result back unchanged. Mounted fresh per stage-1 result (keyed by App).
 */
export default function StagedResults({
  result,
  onRerun,
  onSteer,
  initialSteer = '',
  initialStep = 'publishers',
  running = false,
}: {
  result: CampaignResult
  onRerun?: () => void
  /** Re-runs stage 1 with a steer (App owns it; omit to hide the step-1 box). */
  onSteer?: (steer: string, from?: SteerStep) => void
  /** The steer this stage-1 result was produced with. */
  initialSteer?: string
  /** The step that steer was written on: the result opens there. */
  initialStep?: SteerStep
  running?: boolean
}) {
  const [step, setStep] = useState<Step>(initialStep)
  // Personas come after publishers: the step opens once the publishers are accepted.
  const [personasOpen, setPersonasOpen] = useState(initialStep === 'personas')
  const [steerP, setSteerP] = useState('')
  const [creatives, setCreatives] = useState<Creative[] | null>(null)
  const [config, setConfig] = useState<CampaignConfig | null>(null)
  const [pending, setPending] = useState<'creatives' | 'config' | null>(null)
  const [stepError, setStepError] = useState<StageErr | null>(null)
  const [cardBusy, setCardBusy] = useState<Record<string, boolean>>({})
  const [cardError, setCardError] = useState<Record<string, StageErr | undefined>>({})
  const [configBusy, setConfigBusy] = useState(false)
  const [configError, setConfigError] = useState<StageErr | null>(null)
  // Set on Approve when some ads still carry check flags: approval goes ahead, but says so.
  const [approveWarning, setApproveWarning] = useState<string | null>(null)
  // The budget stage 3 is built at: the landing value at first, then whatever the user last
  // applied on step 3 (kept when the config is rebuilt after a regenerate).
  // Steer boxes (text) and what each step's agent did. Mounted fresh per stage-1 result, so a new
  // campaign (or a step-1 re-run) starts with empty ones for steps 2 and 3.
  const [steer1, setSteer1] = useState(initialSteer)
  const [steer2, setSteer2] = useState('')
  // The step-2 steer the current ads were written with: per-ad Regenerate sends it too.
  const [applied2, setApplied2] = useState('')
  const [steer3, setSteer3] = useState('')
  const [meta2, setMeta2] = useState<StepMeta | undefined>()
  const [meta3, setMeta3] = useState<StepMeta | undefined>()
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

  const gate = result.gate!
  const stage: StagePayload = {
    ...(result.stage_token != null ? { stage_token: result.stage_token } : {}),
    input_text: result.input_text,
    brief: result.brief!,
    gate,
    publishers: result.publishers,
    personas: result.personas,
  }
  const anyCardBusy = Object.values(cardBusy).some(Boolean)

  /**
   * One config request at a time. Starting a new one, regenerating, or leaving step 3 aborts the
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

  const withSteer = (text: string): StagePayload => (text ? { ...stage, steer: text } : stage)

  /** Requests the ads (step 2); with a steer it re-writes them and drops any config built from the old ones. */
  async function writeAds(steer = '') {
    if (creatives && !steer) return goTo('creatives')
    const t = track()
    setPending('creatives')
    setStepError(null)
    setMeta2(undefined)
    try {
      const out = await createCreatives(withSteer(steer), t.signal, steer ? setMeta2 : undefined)
      if (steer) {
        cancelConfig()
        setConfig(null)
        setConfigError(null)
        setApproveWarning(null)
        setMeta3(undefined)
      }
      setCreatives(out)
      setApplied2(steer)
      setStep('creatives')
    } catch (err) {
      if (!isAbort(err)) setStepError(toStageErr(err))
    } finally {
      t.done()
      if (!t.signal.aborted) setPending(null)
    }
  }

  async function regenerate(personaId: string, note: string): Promise<boolean> {
    if (!creatives) return false
    const t = track()
    cancelConfig() // a config built now would describe the old ad
    setCardBusy((b) => ({ ...b, [personaId]: true }))
    setCardError((e) => ({ ...e, [personaId]: undefined }))
    try {
      const fresh = await regenerateCreative({ ...withSteer(applied2), creatives }, personaId, note, t.signal)
      setCreatives((cs) => (cs ?? []).map((c) => (c.persona_id === personaId ? fresh : c)))
      // The approved set changed: the config no longer matches it.
      cancelConfig()
      setConfig(null)
      setMeta3(undefined)
      setConfigError(null)
      setApproveWarning(null)
      // Step 3 is locked while a card is busy, so the user is on step 1 or 2: stay there.
      setStep((s) => (s === 'config' ? 'creatives' : s))
      return true
    } catch (err) {
      if (!isAbort(err)) setCardError((e) => ({ ...e, [personaId]: toStageErr(err) }))
      return false
    } finally {
      t.done()
      if (!t.signal.aborted) setCardBusy((b) => ({ ...b, [personaId]: false }))
    }
  }

  async function approve() {
    if (!creatives) return
    if (config) return goTo('config')
    const t = startConfig()
    setPending('config')
    setStepError(null)
    try {
      setMeta3(undefined)
      const out = await buildConfig({ ...stage, creatives }, budgetChoice, t.signal, setMeta3)
      if (!t.current()) return
      setConfig(out)
      setApproveWarning(flagWarning(creatives, result.personas))
      setConfigError(null)
      setStep('config')
    } catch (err) {
      if (t.current() && !isAbort(err)) setStepError(toStageErr(err))
    } finally {
      t.done()
      if (t.current()) setPending(null)
    }
  }

  /** Re-requests stage 3 at `budget` (null = the recommendation). Keeps the old config on failure. */
  async function updateBudget(budget: number | null, steer = '') {
    if (!creatives) return
    const t = startConfig()
    setConfigBusy(true)
    setConfigError(null)
    try {
      const out = await buildConfig({ ...withSteer(steer), creatives }, budget, t.signal, steer ? setMeta3 : undefined)
      if (!t.current()) return
      setConfig(out)
      // an amount in the steer replaces the field (it's the newer instruction): keep it for later updates
      const steered = steer && out.budget.source === 'user' ? Number(out.budget.monthly_usd) : NaN
      setBudgetChoice(Number.isFinite(steered) ? steered : budget)
    } catch (err) {
      if (t.current() && !isAbort(err)) setConfigError(toStageErr(err))
    } finally {
      t.done()
      if (t.current()) setConfigBusy(false)
    }
  }

  const recCount = result.publishers.filter((p) => p.recommended).length
  const workingNames = {
    personas: result.personas.map((p) => p.name),
    publishers: result.publishers.filter((p) => p.recommended).map((p) => p.name),
  }
  const steps: StepDef<Step>[] = [
    { id: 'publishers', label: 'Publishers', enabled: true },
    { id: 'personas', label: 'Personas', enabled: personasOpen, hint: 'Accept the publishers first.' },
    { id: 'creatives', label: 'Creatives', enabled: !!creatives, hint: 'Write the ads first.' },
    {
      id: 'config',
      label: 'Campaign config',
      enabled: !!config && !anyCardBusy,
      hint: anyCardBusy ? 'Wait for the ad to finish rewriting.' : 'Approve creatives first.',
    },
  ]
  /** A personas steer keeps the publishers steer it was built on (the step-1 box). */
  const personasSteer = (text: string) => {
    const joined = [initialSteer.trim(), text.trim()].filter(Boolean).join('. ')
    return joined.length <= STEER_MAX ? joined : text.trim()
  }
  const testBudget = config?.budget.test_budget === true ? config.budget.monthly_usd : undefined

  const headingCls = 'm-0 text-lg font-semibold tracking-[-0.01em] outline-none sm:text-xl'
  const errorBlock = stepError && (
    <div className="mt-4">
      <StageError err={stepError} onRerun={onRerun} />
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
            {step === 'config' && typeof testBudget === 'number' && (
              <p className="m-0 mt-1 font-semibold">Test budget: {usd(testBudget)} / month</p>
            )}
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
          />
          {onSteer && (
            <AgentSteer
              placeholder="Skip pet stores"
              value={steer1}
              onChange={setSteer1}
              onApply={(t) => onSteer(t, 'publishers')}
              busy={running}
              allowBlank={!!initialSteer}
            />
          )}
          <AgentNotes
            className="mb-5"
            notes={initialSteer && initialStep === 'publishers' ? result.agent_notes : undefined}
          />
          <PublishersTab publishers={result.publishers} config={config} />
          <StepActions>
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
          </StepActions>
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
          />
          {onSteer && (
            <AgentSteer
              placeholder="Drop the Gifter"
              value={steerP}
              onChange={setSteerP}
              onApply={(t) => onSteer(personasSteer(t), 'personas')}
              busy={running}
            />
          )}
          <AgentNotes
            className="mb-5"
            notes={initialSteer && initialStep === 'personas' ? result.agent_notes : undefined}
          />
          <PersonasTab personas={result.personas} publishers={result.publishers} />
          <StepActions>
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
          </StepActions>
          {pending === 'creatives' && <AgentWorking {...workingNames} className="mt-2 justify-end" />}
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
            sub="One ad per persona, each written for one publisher; publishers without their own ad reuse one (the config says which). Regenerate any you'd change — add a note to steer it."
          />
          <AgentSteer
            placeholder="Make them more playful"
            value={steer2}
            onChange={setSteer2}
            onApply={(t) => writeAds(t)}
            busy={pending === 'creatives'}
            disabled={pending === 'config' || anyCardBusy}
          />
          {pending === 'creatives' && <AgentWorking {...workingNames} className="-mt-2 mb-4" />}
          {errorBlock}
          <AgentNotes className="mb-5" notes={meta2?.agent_notes} />
          <PersonasTab
            personas={result.personas}
            creatives={creatives}
            publishers={result.publishers}
            busy={cardBusy}
            actions={(p) => (
              <RegenerateControls
                personaName={p.name}
                busy={!!cardBusy[p.persona_id]}
                disabled={pending === 'config' || (anyCardBusy && !cardBusy[p.persona_id])}
                error={cardError[p.persona_id]}
                onRerun={onRerun}
                onRegenerate={(note) => regenerate(p.persona_id, note)}
              />
            )}
          />
          <StepActions>
            <button type="button" className="pill" onClick={() => goTo('personas')}>
              ← Back to personas
            </button>
            <button
              type="button"
              className="pill pill-primary"
              disabled={pending === 'config' || anyCardBusy}
              onClick={approve}
            >
              {pending === 'config' ? <Busy label="Building config…" /> : 'Approve creatives & build config →'}
            </button>
          </StepActions>
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
          />
          {approveWarning && (
            <p data-testid="approve-warning" role="status" className="m-0 mb-4 rounded-lg border border-[#F0D9B2] bg-[#FBEFDC] px-3 py-2 text-[13px] text-[#5B4520]">
              {approveWarning}
            </p>
          )}
          <AgentSteer
            placeholder="Keep it under $5,000"
            value={steer3}
            onChange={setSteer3}
            onApply={(t) => updateBudget(budgetChoice, t)}
            busy={configBusy}
          />
          <AgentNotes className="mb-5" notes={meta3?.agent_notes} />
          <ConfigStep
            config={config}
            publishers={result.publishers}
            personas={result.personas}
            creatives={creatives ?? []}
            busy={configBusy}
            error={configError}
            onRerun={onRerun}
            onBudget={updateBudget}
          />
          <StepActions>
            <button type="button" className="pill" onClick={() => goTo('creatives')}>
              ← Back to creatives
            </button>
          </StepActions>
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
}: {
  id: string
  title: string
  sub: string
  className: string
  headingRef: React.Ref<HTMLHeadingElement>
}) {
  return (
    <div className="mb-4">
      <h3 id={id} ref={headingRef} tabIndex={-1} className={className}>
        {title}
      </h3>
      <p className="m-0 mt-1 text-[13.5px] text-muted">{sub}</p>
    </div>
  )
}

function StepActions({ children }: { children: React.ReactNode }) {
  return <div className="mt-6 flex flex-wrap items-center justify-end gap-3">{children}</div>
}
