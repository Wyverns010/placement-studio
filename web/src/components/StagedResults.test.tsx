import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CampaignConfig, CampaignResult, Creative } from '../types'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return { ...actual, createCreatives: vi.fn(), regenerateCreative: vi.fn(), buildConfig: vi.fn() }
})
import { ApiError, buildConfig, createCreatives, regenerateCreative } from '../api'
import Results from './Results'

const pub = (id: string, name: string, fit: number, recommended: boolean) => ({
  publisher_id: id,
  name,
  fit,
  factors: [],
  recommended,
  stretch: false,
  reason: `${name} reason`,
})

const result: CampaignResult = {
  input_text: 'premium dog food for senior dogs\n\nAdditional details:\n- q: a',
  budget_usd: null,
  outcome: 'proceed',
  message: null,
  brief: {
    describes_business: true,
    product: 'dog food',
    audience_type: 'consumer',
    categories: ['pet'],
    adjacent_categories: [],
    conflicts: [],
    price_usd: null,
    price_tier: 'premium',
    business_model: 'subscription',
    age_min: null,
    age_max: null,
    gender_skew: 'unknown',
    facts: [],
    unknowns: [],
    self_confidence: 0.9,
  },
  gate: { outcome: 'proceed', confidence: 0.91, threshold: 0.7, impl: 'llm', signals: {} },
  publishers: [pub('p1', 'Pawline', 0.88, true), pub('p2', 'Ruffco', 0.8, true), pub('p3', 'Skipped', 0.1, false)],
  personas: [
    { persona_id: 'a', name: 'Pet Parent', fit: 0.9, factors: [], stretch: false },
    { persona_id: 'b', name: 'Wellness Optimizer', fit: 0.7, factors: [], stretch: false },
  ],
  creatives: [],
  clarify: [],
  config: null,
  stage_token: 'tok_abc',
}

const cr = (persona: string, pubId: string, headline: string): Creative => ({
  creative_id: `cr_${persona}`,
  persona_id: persona,
  publisher_id: pubId,
  headline,
  body: `${headline} body`,
  cta: 'Start a subscription',
  why: 'Because',
  fact_violations: [],
})
const creatives = [cr('a', 'p1', 'Food for old friends'), cr('b', 'p2', 'Joints that keep up')]

const cfg = (monthly: number, source: 'recommended' | 'user', extra: Partial<CampaignConfig> = {}): CampaignConfig => ({
  campaign_id: 'cmp_1',
  objective: 'conversions',
  conversion_event: 'subscription_start',
  budget: { monthly_usd: monthly, recommended_usd: 6000, source, pacing: 'even', unallocated_usd: 0, test_budget: false },
  bid_strategy: { type: 'target_cpa', target_usd: 41 },
  targeting: {},
  line_items: [
    { publisher_id: 'p1', share: 0.6, budget_usd: monthly * 0.6, creative_id: 'cr_a' },
    { publisher_id: 'p2', share: 0.4, budget_usd: monthly * 0.4, creative_id: 'cr_b' },
  ],
  frequency_cap: { impressions: 4, per_days: 14 },
  guardrails: {},
  rationales: {
    budget:
      'Recommended $6,000/mo: $41 target CPA × 50 conversions per line item across 2 publishers, rounded to $500',
    pacing: 'Even: a premium-tier purchase is considered, so reminders are spread out',
    frequency_cap: 'At most 4 impressions per person every 14 days (premium tier, +1 for a subscription)',
  },
  decision_trace: {},
  ...extra,
})

const stage1 = {
  stage_token: 'tok_abc',
  input_text: result.input_text,
  brief: result.brief,
  gate: result.gate,
  publishers: result.publishers,
  personas: result.personas,
}

beforeEach(() => {
  vi.mocked(createCreatives).mockReset().mockResolvedValue(creatives)
  vi.mocked(regenerateCreative).mockReset()
  vi.mocked(buildConfig)
    .mockReset()
    .mockImplementation(async (_p, b) => (b != null ? cfg(b, 'user') : cfg(6000, 'recommended')))
})

const steps = () => within(screen.getByRole('navigation', { name: 'Campaign steps' }))
const stepBtn = (n: RegExp) => steps().getByRole('button', { name: n })

async function toStep2(user: ReturnType<typeof userEvent.setup>, r: CampaignResult = result) {
  render(<Results result={r} onBack={() => {}} displayText="premium dog food for senior dogs" />)
  await user.click(screen.getByRole('button', { name: /write ads for these publishers/i }))
  await screen.findByRole('article', { name: 'Pet Parent' })
}

async function toStep3(user: ReturnType<typeof userEvent.setup>, r: CampaignResult = result) {
  await toStep2(user, r)
  await user.click(screen.getByRole('button', { name: /approve creatives & build config/i }))
  await screen.findByLabelText('Monthly budget in USD')
}

describe('Staged results', () => {
  it('starts on step 1 with publishers and the persona list, no ads; later steps locked', () => {
    render(<Results result={result} onBack={() => {}} />)
    expect(stepBtn(/publishers & personas/i)).toHaveAttribute('aria-current', 'step')
    expect(stepBtn(/creatives/i)).toHaveAttribute('aria-disabled', 'true')
    expect(stepBtn(/campaign config/i)).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('article', { name: 'Pawline' })).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'Pet Parent' })).toBeInTheDocument()
    expect(screen.queryByText(/sponsored/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/no creative generated/i)).not.toBeInTheDocument()
  })

  it('shows the typed text in the header, not the text with answers appended', () => {
    render(<Results result={result} onBack={() => {}} displayText="premium dog food for senior dogs" />)
    expect(screen.getByText('“premium dog food for senior dogs”')).toBeInTheDocument()
  })

  it('requests creatives with the unchanged stage-1 payload and shows the ad cards', async () => {
    const user = userEvent.setup()
    await toStep2(user)
    expect(createCreatives).toHaveBeenCalledTimes(1)
    expect(vi.mocked(createCreatives).mock.calls[0][0]).toEqual(stage1)
    expect(stepBtn(/creatives/i)).toHaveAttribute('aria-current', 'step')
    expect(screen.getByText('Food for old friends')).toBeInTheDocument()
    expect(screen.getByText('Sponsored · on Ruffco')).toBeInTheDocument()
  })

  it('shows a busy button while writing ads, and an inline error (no spinner) on failure', async () => {
    const user = userEvent.setup()
    let reject!: (e: Error) => void
    vi.mocked(createCreatives).mockReturnValueOnce(new Promise((_, r) => (reject = r)))
    render(<Results result={result} onBack={() => {}} />)
    await user.click(screen.getByRole('button', { name: /write ads for these publishers/i }))
    expect(screen.getByRole('button', { name: /writing ads/i })).toBeDisabled()
    reject(new ApiError(429, 'Too many runs'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many runs')
    expect(screen.queryByText(/writing ads/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /write ads for these publishers/i })).toBeEnabled()
    expect(stepBtn(/creatives/i)).toHaveAttribute('aria-disabled', 'true')
  })

  it('back navigation keeps the ads; going forward again does not re-request them', async () => {
    const user = userEvent.setup()
    await toStep2(user)
    await user.click(stepBtn(/publishers & personas/i))
    expect(stepBtn(/publishers & personas/i)).toHaveAttribute('aria-current', 'step')
    expect(screen.getByRole('article', { name: 'Pawline' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /write ads for these publishers/i }))
    expect(screen.getByText('Food for old friends')).toBeInTheDocument()
    expect(createCreatives).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: /back to publishers/i }))
    expect(stepBtn(/publishers & personas/i)).toHaveAttribute('aria-current', 'step')
  })

  it('steps are keyboard reachable: arrow keys move between unlocked steps', async () => {
    const user = userEvent.setup()
    await toStep2(user)
    stepBtn(/creatives/i).focus()
    await user.keyboard('{ArrowLeft}')
    expect(stepBtn(/publishers & personas/i)).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(stepBtn(/publishers & personas/i)).toHaveAttribute('aria-current', 'step')
  })

  it('regenerate sends the note and replaces only that card', async () => {
    const user = userEvent.setup()
    vi.mocked(regenerateCreative).mockResolvedValueOnce(cr('a', 'p1', 'Warmer words'))
    await toStep2(user)
    const card = screen.getByRole('article', { name: 'Pet Parent' })
    await user.type(within(card).getByRole('textbox', { name: /note/i }), 'warmer, mention the refill')
    await user.click(within(card).getByRole('button', { name: /regenerate/i }))
    expect(regenerateCreative).toHaveBeenCalledWith(
      { ...stage1, creatives },
      'a',
      'warmer, mention the refill',
      expect.any(AbortSignal),
    )
    expect(await within(card).findByText('Warmer words')).toBeInTheDocument()
    expect(within(card).queryByText('Food for old friends')).not.toBeInTheDocument()
    expect(screen.getByText('Joints that keep up')).toBeInTheDocument()
    expect(within(card).getByRole('textbox', { name: /note/i })).toHaveValue('')
  })

  it('caps the note at 200 characters', async () => {
    const user = userEvent.setup()
    await toStep2(user)
    const card = screen.getByRole('article', { name: 'Pet Parent' })
    expect(within(card).getByRole('textbox', { name: /note/i })).toHaveAttribute('maxLength', '200')
  })

  it('a regenerating card is busy on its own; its error is inline and the spinner goes away', async () => {
    const user = userEvent.setup()
    let reject!: (e: Error) => void
    vi.mocked(regenerateCreative).mockReturnValueOnce(new Promise((_, r) => (reject = r)))
    await toStep2(user)
    const a = screen.getByRole('article', { name: 'Pet Parent' })
    const b = screen.getByRole('article', { name: 'Wellness Optimizer' })
    await user.click(within(a).getByRole('button', { name: /regenerate/i }))
    expect(a).toHaveAttribute('aria-busy', 'true')
    expect(within(a).getByRole('button', { name: /rewriting/i })).toBeDisabled()
    expect(b).not.toHaveAttribute('aria-busy', 'true')
    expect(within(b).getByRole('button', { name: /regenerate/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /approve creatives/i })).toBeDisabled()
    reject(new ApiError(502, "The AI service didn't respond"))
    expect(await within(a).findByRole('alert')).toHaveTextContent("didn't respond")
    expect(within(a).queryByText(/rewriting/i)).not.toBeInTheDocument()
    expect(a).not.toHaveAttribute('aria-busy', 'true')
    expect(within(a).getByText('Food for old friends')).toBeInTheDocument()
    expect(within(b).queryByRole('alert')).not.toBeInTheDocument()
  })

  it('approve builds the config with the current creatives at the recommended budget', async () => {
    const user = userEvent.setup()
    await toStep3(user)
    expect(buildConfig).toHaveBeenCalledWith(
      { ...stage1, gate: result.gate, creatives },
      null,
      expect.any(AbortSignal),
    )
    expect(stepBtn(/campaign config/i)).toHaveAttribute('aria-current', 'step')
    expect(screen.getByLabelText('Monthly budget in USD')).toHaveValue('6,000')
    expect(screen.getByText(/Recommended \$6,000 — based on \$41 target CPA/)).toBeInTheDocument()
    expect(screen.getByTestId('budget-source')).toHaveTextContent(/recommended/i)
    expect(screen.getByText(/Target CPA · \$41/)).toBeInTheDocument()
    expect(screen.getAllByText(/Even: a premium-tier purchase/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/At most 4 impressions per person/).length).toBeGreaterThan(0)
  })

  it('passes the budget the user gave on the landing page to the first config', async () => {
    const user = userEvent.setup()
    await toStep3(user, { ...result, budget_usd: 9000 })
    expect(vi.mocked(buildConfig).mock.calls[0][1]).toBe(9000)
    expect(screen.getByTestId('budget-source')).toHaveTextContent(/yours/i)
  })

  it('editing the budget re-requests the config and shows it as yours; reset goes back', async () => {
    const user = userEvent.setup()
    await toStep3(user)
    const input = screen.getByLabelText('Monthly budget in USD')
    await user.clear(input)
    await user.type(input, '12000')
    await user.click(screen.getByRole('button', { name: 'Update' }))
    expect(vi.mocked(buildConfig).mock.calls.at(-1)![1]).toBe(12000)
    await waitFor(() => expect(screen.getByTestId('budget-source')).toHaveTextContent(/yours/i))
    expect(screen.getByLabelText('Monthly budget in USD')).toHaveValue('12,000')
    expect(screen.getByText(/\$12,000 \/ month/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /use recommended/i }))
    expect(vi.mocked(buildConfig).mock.calls.at(-1)![1]).toBeNull()
    await waitFor(() => expect(screen.getByTestId('budget-source')).toHaveTextContent(/recommended/i))
  })

  it('an out-of-range budget is rejected inline without a request', async () => {
    const user = userEvent.setup()
    await toStep3(user)
    const input = screen.getByLabelText('Monthly budget in USD')
    await user.clear(input)
    await user.type(input, '100')
    expect(screen.getByRole('button', { name: 'Update' })).toBeDisabled()
    expect(screen.getByText(/between \$500 and \$5,000,000/)).toBeInTheDocument()
    expect(buildConfig).toHaveBeenCalledTimes(1)
  })

  it('a failed config update keeps the old config and shows the error, no spinner', async () => {
    const user = userEvent.setup()
    await toStep3(user)
    vi.mocked(buildConfig).mockRejectedValueOnce(new ApiError(422, 'Budget not allowed'))
    const input = screen.getByLabelText('Monthly budget in USD')
    await user.clear(input)
    await user.type(input, '7000')
    await user.click(screen.getByRole('button', { name: 'Update' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Budget not allowed')
    expect(screen.queryByText(/updating/i)).not.toBeInTheDocument()
    expect(screen.getByText(/\$6,000 \/ month/)).toBeInTheDocument()
  })

  it('a failed approve shows the error on step 2 and leaves no spinner', async () => {
    const user = userEvent.setup()
    vi.mocked(buildConfig).mockRejectedValueOnce(new ApiError(500, 'Config broke'))
    await toStep2(user)
    await user.click(screen.getByRole('button', { name: /approve creatives & build config/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Config broke')
    expect(screen.queryByText(/building config/i)).not.toBeInTheDocument()
    expect(stepBtn(/creatives/i)).toHaveAttribute('aria-current', 'step')
    expect(stepBtn(/campaign config/i)).toHaveAttribute('aria-disabled', 'true')
  })

  it('regenerating after approval clears the config and stays on step 2', async () => {
    const user = userEvent.setup()
    await toStep3(user)
    await user.click(stepBtn(/creatives/i))
    vi.mocked(regenerateCreative).mockResolvedValueOnce(cr('b', 'p2', 'New joints line'))
    const card = screen.getByRole('article', { name: 'Wellness Optimizer' })
    await user.click(within(card).getByRole('button', { name: /regenerate/i }))
    expect(await within(card).findByText('New joints line')).toBeInTheDocument()
    expect(stepBtn(/creatives/i)).toHaveAttribute('aria-current', 'step')
    expect(stepBtn(/campaign config/i)).toHaveAttribute('aria-disabled', 'true')
    await user.click(screen.getByRole('button', { name: /approve creatives & build config/i }))
    await screen.findByLabelText('Monthly budget in USD')
    expect(vi.mocked(buildConfig).mock.calls.at(-1)![0].creatives[1].headline).toBe('New joints line')
  })

  it('a 403 (campaign changed or expired) offers Run it again, which re-runs stage 1', async () => {
    const user = userEvent.setup()
    const onRerun = vi.fn()
    vi.mocked(createCreatives).mockRejectedValueOnce(
      new ApiError(403, 'This campaign changed or expired — run it again.'),
    )
    render(<Results result={result} onBack={() => {}} onRerun={onRerun} />)
    await user.click(screen.getByRole('button', { name: /write ads for these publishers/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/changed or expired/)
    await user.click(screen.getByRole('button', { name: /run it again/i }))
    expect(onRerun).toHaveBeenCalledTimes(1)
  })

  it('a 403 on regenerate shows Run it again inside that card', async () => {
    const user = userEvent.setup()
    const onRerun = vi.fn()
    vi.mocked(regenerateCreative).mockRejectedValueOnce(
      new ApiError(403, 'This campaign changed or expired — run it again.'),
    )
    render(<Results result={result} onBack={() => {}} onRerun={onRerun} />)
    await user.click(screen.getByRole('button', { name: /write ads for these publishers/i }))
    const card = await screen.findByRole('article', { name: 'Pet Parent' })
    await user.click(within(card).getByRole('button', { name: /regenerate/i }))
    await user.click(await within(card).findByRole('button', { name: /run it again/i }))
    expect(onRerun).toHaveBeenCalled()
  })

  it('a non-403 error offers no Run it again', async () => {
    const user = userEvent.setup()
    vi.mocked(createCreatives).mockRejectedValueOnce(new ApiError(502, 'AI down'))
    render(<Results result={result} onBack={() => {}} onRerun={() => {}} />)
    await user.click(screen.getByRole('button', { name: /write ads for these publishers/i }))
    await screen.findByRole('alert')
    expect(screen.queryByRole('button', { name: /run it again/i })).not.toBeInTheDocument()
  })

  it('a locked step stays focusable, says why, and does not open', async () => {
    const user = userEvent.setup()
    render(<Results result={result} onBack={() => {}} />)
    const cfgStep = stepBtn(/campaign config/i)
    expect(cfgStep).toBeEnabled()
    expect(cfgStep).toHaveAccessibleDescription('Approve creatives first.')
    await user.click(cfgStep)
    expect(screen.getByRole('status')).toHaveTextContent('Approve creatives first.')
    expect(stepBtn(/publishers & personas/i)).toHaveAttribute('aria-current', 'step')
  })

  it('a stale config response (after leaving step 3 and regenerating) is ignored', async () => {
    const user = userEvent.setup()
    await toStep3(user)
    let resolve!: (c: CampaignConfig) => void
    vi.mocked(buildConfig).mockReturnValueOnce(new Promise((r) => (resolve = r)))
    const input = screen.getByLabelText('Monthly budget in USD')
    await user.clear(input)
    await user.type(input, '12000')
    await user.click(screen.getByRole('button', { name: 'Update' }))
    // leave step 3 while the update is in flight, then regenerate (clears the config)
    await user.click(stepBtn(/creatives/i))
    vi.mocked(regenerateCreative).mockResolvedValueOnce(cr('a', 'p1', 'Fresh line'))
    const card = screen.getByRole('article', { name: 'Pet Parent' })
    await user.click(within(card).getByRole('button', { name: /regenerate/i }))
    await within(card).findByText('Fresh line')
    resolve(cfg(12000, 'user'))
    await new Promise((r) => setTimeout(r, 20))
    expect(stepBtn(/campaign config/i)).toHaveAttribute('aria-disabled', 'true')
  })

  it('a stale config response after leaving step 3 does not replace the shown config', async () => {
    const user = userEvent.setup()
    await toStep3(user)
    let resolve!: (c: CampaignConfig) => void
    vi.mocked(buildConfig).mockReturnValueOnce(new Promise((r) => (resolve = r)))
    const input = screen.getByLabelText('Monthly budget in USD')
    await user.clear(input)
    await user.type(input, '12000')
    await user.click(screen.getByRole('button', { name: 'Update' }))
    await user.click(stepBtn(/creatives/i))
    resolve(cfg(12000, 'user'))
    await new Promise((r) => setTimeout(r, 20))
    await user.click(stepBtn(/campaign config/i))
    expect(screen.getByText(/\$6,000 \/ month/)).toBeInTheDocument()
    expect(screen.getByTestId('budget-source')).toHaveTextContent(/recommended/i)
    expect(screen.queryByText(/updating/i)).not.toBeInTheDocument()
  })

  it('a blank budget + Update requests the recommendation (budget omitted)', async () => {
    const user = userEvent.setup()
    await toStep3(user, { ...result, budget_usd: 9000 })
    await user.clear(screen.getByLabelText('Monthly budget in USD'))
    await user.click(screen.getByRole('button', { name: 'Update' }))
    expect(vi.mocked(buildConfig).mock.calls.at(-1)![1]).toBeNull()
  })

  it('accepts "$12,000.00" on step 3 and rejects "1e3"', async () => {
    const user = userEvent.setup()
    await toStep3(user)
    const input = screen.getByLabelText('Monthly budget in USD')
    await user.clear(input)
    await user.type(input, '1e3')
    expect(screen.getByRole('button', { name: 'Update' })).toBeDisabled()
    await user.clear(input)
    await user.type(input, '$12,000.00')
    await user.click(screen.getByRole('button', { name: 'Update' }))
    expect(vi.mocked(buildConfig).mock.calls.at(-1)![1]).toBe(12000)
  })

  it('rebuilding after a regenerate keeps the budget last chosen on step 3', async () => {
    const user = userEvent.setup()
    await toStep3(user, { ...result, budget_usd: 9000 })
    const input = screen.getByLabelText('Monthly budget in USD')
    await user.clear(input)
    await user.type(input, '15000')
    await user.click(screen.getByRole('button', { name: 'Update' }))
    await waitFor(() => expect(screen.getByLabelText('Monthly budget in USD')).toHaveValue('15,000'))
    await user.click(stepBtn(/creatives/i))
    vi.mocked(regenerateCreative).mockResolvedValueOnce(cr('a', 'p1', 'Fresh line'))
    const card = screen.getByRole('article', { name: 'Pet Parent' })
    await user.click(within(card).getByRole('button', { name: /regenerate/i }))
    await within(card).findByText('Fresh line')
    await user.click(screen.getByRole('button', { name: /approve creatives & build config/i }))
    expect(vi.mocked(buildConfig).mock.calls.at(-1)![1]).toBe(15000)
  })

  it('a regenerate that finishes after the user went back to step 1 leaves them there', async () => {
    const user = userEvent.setup()
    let resolve!: (c: Creative) => void
    vi.mocked(regenerateCreative).mockReturnValueOnce(new Promise((r) => (resolve = r)))
    await toStep2(user)
    const card = screen.getByRole('article', { name: 'Pet Parent' })
    await user.click(within(card).getByRole('button', { name: /regenerate/i }))
    await user.click(stepBtn(/publishers & personas/i))
    resolve(cr('a', 'p1', 'Fresh line'))
    await new Promise((r) => setTimeout(r, 20))
    expect(stepBtn(/publishers & personas/i)).toHaveAttribute('aria-current', 'step')
    await user.click(stepBtn(/creatives/i))
    expect(screen.getByText('Fresh line')).toBeInTheDocument()
  })

  it('weak_fit keeps its banner on every step and shows the test budget on step 3', async () => {
    const user = userEvent.setup()
    vi.mocked(buildConfig).mockResolvedValue(
      cfg(1200, 'recommended', {
        budget: { monthly_usd: 1200, recommended_usd: 1200, source: 'recommended', pacing: 'front_loaded', unallocated_usd: 0, test_budget: true },
      }),
    )
    const weak = { ...result, outcome: 'weak_fit' as const, message: 'Few publishers match this closely.' }
    render(<Results result={weak} onBack={() => {}} />)
    expect(screen.getByText('Few publishers match this closely.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /write ads for these publishers/i }))
    await screen.findByText('Food for old friends')
    expect(screen.getByText('Few publishers match this closely.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /approve creatives & build config/i }))
    expect(await screen.findByText('Test budget: $1,200 / month')).toBeInTheDocument()
    expect(screen.getByText('Few publishers match this closely.')).toBeInTheDocument()
    expect(screen.getByText(/front loaded pacing/i)).toBeInTheDocument()
  })
})
