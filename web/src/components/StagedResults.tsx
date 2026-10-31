import { useEffect, useRef, useState } from 'react'
import { ApiError, buildConfig, createCreatives, regenerateCreative } from '../api'
import { usd } from '../format'
import type { CampaignConfig, CampaignResult, Creative, StagePayload } from '../types'
import ConfigStep from './ConfigStep'
import OutcomeBanner from './OutcomeBanner'
import PersonasTab from './PersonasTab'
import PublishersTab from './PublishersTab'
import RegenerateControls from './RegenerateControls'
import Stepper, { type StepDef } from './Stepper'
import { Busy, StageError, type StageErr } from './ui'

type Step = 'publishers' | 'creatives' | 'config'

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
}: {
  result: CampaignResult
  onRerun?: () => void
}) {
  const [step, setStep] = useState<Step>('publishers')
  const [creatives, setCreatives] = useState<Creative[] | null>(null)
  const [config, setConfig] = useState<CampaignConfig | null>(null)
  const [pending, setPending] = useState<'creatives' | 'config' | null>(null)
  const [stepError, setStepError] = useState<StageErr | null>(null)
  const [cardBusy, setCardBusy] = useState<Record<string, boolean>>({})
  const [cardError, setCardError] = useState<Record<string, StageErr | undefined>>({})
  const [configBusy, setConfigBusy] = useState(false)
  const [configError, setConfigError] = useState<StageErr | null>(null)
  // The budget stage 3 is built at: the landing value at first, then whatever the user last
  // applied on step 3 (kept when the config is rebuilt after a regenerate).
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

  async function writeAds() {
    if (creatives) return goTo('creatives')
    const t = track()
    setPending('creatives')
    setStepError(null)
    try {
      const out = await createCreatives(stage, t.signal)
      setCreatives(out)
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
      const fresh = await regenerateCreative({ ...stage, creatives }, personaId, note, t.signal)
      setCreatives((cs) => (cs ?? []).map((c) => (c.persona_id === personaId ? fresh : c)))
      // The approved set changed: the config no longer matches it.
      cancelConfig()
      setConfig(null)
      setConfigError(null)
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
      const out = await buildConfig({ ...stage, creatives }, budgetChoice, t.signal)
      if (!t.current()) return
      setConfig(out)
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
  async function updateBudget(budget: number | null) {
    if (!creatives) return
    const t = startConfig()
    setConfigBusy(true)
    setConfigError(null)
    try {
      const out = await buildConfig({ ...stage, creatives }, budget, t.signal)
      if (!t.current()) return
      setConfig(out)
      setBudgetChoice(budget)
    } catch (err) {
      if (t.current() && !isAbort(err)) setConfigError(toStageErr(err))
    } finally {
      t.done()
      if (t.current()) setConfigBusy(false)
    }
  }

  const recCount = result.publishers.filter((p) => p.recommended).length
  const steps: StepDef<Step>[] = [
    { id: 'publishers', label: 'Publishers & personas', enabled: true },
    { id: 'creatives', label: 'Creatives', enabled: !!creatives, hint: 'Write the ads first.' },
    {
      id: 'config',
      label: 'Campaign config',
      enabled: !!config && !anyCardBusy,
      hint: anyCardBusy ? 'Wait for the ad to finish rewriting.' : 'Approve creatives first.',
    },
  ]
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
          <OutcomeBanner variant="amber" title="Weak fit — treat this as a test.">
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
            title={`${recCount} publisher${recCount === 1 ? '' : 's'} and ${result.personas.length} persona${result.personas.length === 1 ? '' : 's'}`}
            sub="Where your ads will run and who they're written for."
          />
          <PublishersTab publishers={result.publishers} config={config} />
          <h4 className="m-0 mt-8 mb-3 text-[13px] font-semibold tracking-[0.06em] text-muted uppercase">
            Personas · {result.personas.length}
          </h4>
          <PersonasTab personas={result.personas} publishers={result.publishers} />
          <StepActions>
            <button
              type="button"
              className="pill pill-primary"
              disabled={pending === 'creatives' || recCount === 0 || result.personas.length === 0}
              onClick={writeAds}
            >
              {pending === 'creatives' ? <Busy label="Writing ads…" /> : 'Write ads for these publishers →'}
            </button>
          </StepActions>
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
            sub="One ad per persona, written for the publisher it runs on. Regenerate any you'd change — add a note to steer it."
          />
          <PersonasTab
            personas={result.personas}
            creatives={creatives}
            publishers={result.publishers}
            busy={cardBusy}
            actions={(p) => (
              <RegenerateControls
                personaName={p.name}
                busy={!!cardBusy[p.persona_id]}
                disabled={pending === 'config'}
                error={cardError[p.persona_id]}
                onRerun={onRerun}
                onRegenerate={(note) => regenerate(p.persona_id, note)}
              />
            )}
          />
          <StepActions>
            <button type="button" className="pill" onClick={() => goTo('publishers')}>
              ← Back to publishers
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
          {errorBlock}
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
