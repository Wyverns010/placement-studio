import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CampaignConfig, CampaignResult, Creative, StepMeta } from '../types'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return { ...actual, createCreatives: vi.fn(), regenerateCreative: vi.fn(), buildConfig: vi.fn() }
})
import { ApiError, buildConfig, createCreatives, regenerateCreative } from '../api'
import Results from './Results'

const pub = (id: string, name: string, rec: boolean) => ({
  publisher_id: id, name, fit: 0.8, factors: [], recommended: rec, stretch: false, reason: 'r',
})
const result: CampaignResult = {
  input_text: 'dog food',
  budget_usd: null,
  outcome: 'proceed',
  message: null,
  brief: { categories: ['pet'], price_tier: 'premium', business_model: 'subscription' } as CampaignResult['brief'],
  gate: { outcome: 'proceed', confidence: 0.9, threshold: 0.7, impl: 'llm', signals: {} },
  publishers: [pub('p1', 'Pawline', true), pub('p2', 'Ruffco', true)],
  personas: [{ persona_id: 'a', name: 'Pet Parent', fit: 0.9, factors: [], stretch: false }],
  creatives: [],
  clarify: [],
  config: null,
  stage_token: 'tok',
  mode: 'agent',
  agent_notes: ['Left out Skipped (pet) because of your note.'],
  agent_trace: [{ agent: 'strategist', tool: 'rank_publishers', args_summary: '{}', result_summary: 'ok', ms: 2 }],
}
const cr: Creative = {
  creative_id: 'cr_a', persona_id: 'a', publisher_id: 'p1', headline: 'Food for old friends', body: 'b', cta: 'Go', why: 'w', fact_violations: [],
}
const cfg = (monthly: number): CampaignConfig => ({
  campaign_id: 'c', objective: 'conversions', conversion_event: 'purchase',
  budget: { monthly_usd: monthly, recommended_usd: 6000, source: 'recommended', pacing: 'even', unallocated_usd: 0, test_budget: false },
  bid_strategy: {}, targeting: {}, line_items: [], frequency_cap: {}, guardrails: {}, rationales: {}, decision_trace: {},
})

beforeEach(() => {
  vi.mocked(createCreatives).mockReset().mockImplementation(async (_p, _s, onMeta) => {
    onMeta?.({ mode: 'agent', agent_notes: ['Made the ads playful.'], agent_trace: [{ agent: 'copywriter', tool: 'write_ad', ms: 5 }] })
    return [cr]
  })
  vi.mocked(buildConfig).mockReset().mockImplementation(async (_p, _b, _s, onMeta) => {
    onMeta?.({ mode: 'code' } as StepMeta)
    return cfg(6000)
  })
})

const applyAt = async (user: ReturnType<typeof userEvent.setup>, text: string) => {
  await user.type(screen.getByLabelText('Tell the agent'), text)
  await user.click(screen.getByRole('button', { name: 'Apply' }))
}

describe('step agents UI', () => {
  it('step 1: Apply calls onSteer with the text; notes show only for a steered result, with no agent panel', async () => {
    const user = userEvent.setup()
    const onSteer = vi.fn()
    const { rerender } = render(<Results result={result} onBack={() => {}} onSteer={onSteer} />)
    expect(screen.queryByText('Left out Skipped (pet) because of your note.')).not.toBeInTheDocument()
    rerender(<Results result={result} onBack={() => {}} onSteer={onSteer} steer="Skip pet stores" />)
    expect(screen.getByPlaceholderText(/skip pet stores/i)).toBeInTheDocument()
    expect(screen.getByText('Left out Skipped (pet) because of your note.')).toBeInTheDocument()
    expect(screen.queryByText(/what the agent did/i)).not.toBeInTheDocument()
    await applyAt(user, 'Skip pet stores')
    expect(onSteer).toHaveBeenCalledWith('Skip pet stores')
  })

  it('step 2: Apply re-requests creatives with the steer; the first request has none', async () => {
    const user = userEvent.setup()
    render(<Results result={result} onBack={() => {}} />)
    await user.click(screen.getByRole('button', { name: /write ads for these publishers/i }))
    await screen.findByText('Food for old friends')
    expect(vi.mocked(createCreatives).mock.calls[0][0]).not.toHaveProperty('steer')
    expect(screen.getByPlaceholderText(/make them more playful/i)).toBeInTheDocument()
    await applyAt(user, 'Make them more playful')
    await waitFor(() => expect(createCreatives).toHaveBeenCalledTimes(2))
    expect(vi.mocked(createCreatives).mock.calls[1][0]).toMatchObject({ steer: 'Make them more playful' })
    expect(await screen.findByText('Made the ads playful.')).toBeInTheDocument()
  })

  it('step 2: a 422 steer error shows inline', async () => {
    const user = userEvent.setup()
    render(<Results result={result} onBack={() => {}} />)
    await user.click(screen.getByRole('button', { name: /write ads for these publishers/i }))
    await screen.findByText('Food for old friends')
    vi.mocked(createCreatives).mockRejectedValueOnce(new ApiError(422, 'Keep the note to 300 characters.'))
    await applyAt(user, 'x')
    expect(await screen.findByRole('alert')).toHaveTextContent('Keep the note to 300 characters.')
  })

  it('step 3: Apply re-requests config with the steer and shows its notes', async () => {
    const user = userEvent.setup()
    render(<Results result={result} onBack={() => {}} />)
    await user.click(screen.getByRole('button', { name: /write ads for these publishers/i }))
    await screen.findByText('Food for old friends')
    await user.click(screen.getByRole('button', { name: /approve creatives & build config/i }))
    await screen.findByLabelText('Monthly budget in USD')
    expect(vi.mocked(buildConfig).mock.calls[0][0]).not.toHaveProperty('steer')
    expect(screen.getByPlaceholderText(/keep it under \$5,000/i)).toBeInTheDocument()
    vi.mocked(buildConfig).mockImplementationOnce(async (_p, _b, _s, onMeta) => {
      onMeta?.({ mode: 'fallback', agent_notes: ['Agent stopped; code result used.'] })
      return cfg(4900)
    })
    await applyAt(user, 'Keep it under $5,000')
    await waitFor(() => expect(buildConfig).toHaveBeenCalledTimes(2))
    expect(vi.mocked(buildConfig).mock.calls[1][0]).toMatchObject({ steer: 'Keep it under $5,000' })
    expect(await screen.findByText('Agent stopped; code result used.')).toBeInTheDocument()
  })

  it('step 2: per-ad Regenerate sends the step steer that was applied', async () => {
    const user = userEvent.setup()
    vi.mocked(regenerateCreative).mockReset().mockResolvedValue({ ...cr, headline: 'Fresh take' })
    render(<Results result={result} onBack={() => {}} />)
    await user.click(screen.getByRole('button', { name: /write ads for these publishers/i }))
    await screen.findByText('Food for old friends')
    await user.click(screen.getByRole('button', { name: /^regenerate/i }))
    await waitFor(() => expect(regenerateCreative).toHaveBeenCalledTimes(1))
    expect(vi.mocked(regenerateCreative).mock.calls[0][0]).not.toHaveProperty('steer')
    await applyAt(user, 'Make them more playful')
    await waitFor(() => expect(createCreatives).toHaveBeenCalledTimes(2))
    await screen.findByText('Food for old friends')
    await user.click(screen.getByRole('button', { name: /^regenerate/i }))
    await waitFor(() => expect(regenerateCreative).toHaveBeenCalledTimes(2))
    expect(vi.mocked(regenerateCreative).mock.calls[1][0]).toMatchObject({ steer: 'Make them more playful' })
  })

  it('step 2: a long ad run says what the team is doing', async () => {
    const user = userEvent.setup()
    vi.mocked(createCreatives).mockImplementationOnce(() => new Promise(() => {}))
    render(<Results result={result} onBack={() => {}} />)
    await user.click(screen.getByRole('button', { name: /write ads for these publishers/i }))
    const status = await screen.findByTestId('agent-working')
    expect(status).toHaveTextContent(/Reading what .+ cares about…/)
  })
})
