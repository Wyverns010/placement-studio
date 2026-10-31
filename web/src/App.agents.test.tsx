import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CampaignResult, Sample, StageEvent } from './types'

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api')
  return { ...actual, getSamples: vi.fn(), runCampaign: vi.fn(), streamCampaign: vi.fn(), createCreatives: vi.fn() }
})
import { getSamples, streamCampaign } from './api'
import App from './App'

const samples: Sample[] = [
  { id: 1, label: 'Senior dog food', text: 'premium dog food for senior dogs' },
  { id: 2, label: 'Candles', text: 'hand-poured candles' },
]
const result = {
  input_text: samples[0].text,
  budget_usd: null,
  outcome: 'proceed',
  message: null,
  brief: { categories: ['pet'], price_tier: 'premium', business_model: 'subscription' },
  gate: { outcome: 'proceed', confidence: 0.91, threshold: 0.7, impl: 'llm', signals: {} },
  publishers: [{ publisher_id: 'p1', name: 'Pawline', fit: 0.8, factors: [], recommended: true, stretch: false, reason: '' }],
  personas: [{ persona_id: 'a', name: 'Pet Parent', fit: 0.9, factors: [], stretch: false }],
  creatives: [],
  clarify: [],
  config: null,
  mode: 'agent',
} as unknown as CampaignResult

let emit!: (e: StageEvent) => void
beforeEach(() => {
  vi.mocked(getSamples).mockReset().mockResolvedValue(samples)
  window.matchMedia = ((q: string) => ({
    matches: q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {}, onchange: null, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
  vi.mocked(streamCampaign).mockReset().mockImplementation((_req, onEvent) => {
    emit = onEvent
    return () => {}
  })
})

async function toResults(user: ReturnType<typeof userEvent.setup>) {
  render(<App />)
  await waitFor(() => expect(screen.getByLabelText('Describe your brand')).toHaveValue(samples[0].text))
  await user.click(screen.getByRole('button', { name: /build campaign/i }))
  act(() => emit({ stage: 'done', data: result as unknown as Record<string, unknown> }))
  await screen.findByRole('navigation', { name: 'Campaign steps' })
}

describe('step agents in App', () => {
  it('SSE agent events update the ticker in the reading panel', async () => {
    window.matchMedia = ((q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
    const user = userEvent.setup()
    render(<App />)
    await waitFor(() => expect(screen.getByLabelText('Describe your brand')).toHaveValue(samples[0].text))
    await user.click(screen.getByRole('button', { name: /build campaign/i }))
    const panel = within(screen.getByRole('complementary', { name: /how we read your brand/i }))
    expect(panel.queryByTestId('agent-ticker')).not.toBeInTheDocument()
    act(() => emit({ stage: 'agent', data: { agent: 'strategist', tool: 'decide', ms: 0 } }))
    expect(panel.getByTestId('agent-ticker')).toHaveTextContent('Agent: decide …')
    act(() => emit({ stage: 'agent', data: { agent: 'strategist', tool: 'rank_publishers', ms: 3 } }))
    expect(panel.getByTestId('agent-ticker')).toHaveTextContent('Agent: rank_publishers …')
  })

  it('step 1 Apply re-streams with the same text and the steer', async () => {
    const user = userEvent.setup()
    await toResults(user)
    await user.type(screen.getByLabelText('Tell the agent'), 'Skip pet stores')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    const req = vi.mocked(streamCampaign).mock.calls.at(-1)![0]
    expect(req).toMatchObject({ text: samples[0].text, steer: 'Skip pet stores' })
    // live agent events show the ticker while it re-runs
    act(() => emit({ stage: 'agent', data: { agent: 'strategist', tool: 'adjust_brief', ms: 1 } }))
    expect(screen.getByTestId('agent-ticker')).toHaveTextContent('Agent: adjust_brief …')
    act(() => emit({ stage: 'done', data: result as unknown as Record<string, unknown> }))
    // the steer stays visible on the new result
    await waitFor(() => expect(screen.getByLabelText('Tell the agent')).toHaveValue('Skip pet stores'))
  })

  it('a new campaign clears the steer', async () => {
    const user = userEvent.setup()
    await toResults(user)
    await user.type(screen.getByLabelText('Tell the agent'), 'Skip pet stores')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    act(() => emit({ stage: 'done', data: result as unknown as Record<string, unknown> }))
    await waitFor(() => expect(screen.getByLabelText('Tell the agent')).toHaveValue('Skip pet stores'))
    // start a different campaign from the home view
    await user.click(screen.getByRole('button', { name: /placement studio home/i }))
    await user.click(screen.getByRole('button', { name: /build campaign/i }))
    expect(vi.mocked(streamCampaign).mock.calls.at(-1)![0]).not.toHaveProperty('steer')
    act(() => emit({ stage: 'done', data: result as unknown as Record<string, unknown> }))
    await waitFor(() => expect(screen.getByLabelText('Tell the agent')).toHaveValue(''))
  })
})
