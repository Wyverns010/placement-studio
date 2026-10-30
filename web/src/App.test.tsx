import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CampaignResult, Sample } from './types'

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api')
  return { ...actual, getSamples: vi.fn(), runCampaign: vi.fn() }
})
import { ApiError, getSamples, runCampaign } from './api'
import App from './App'

const samples: Sample[] = [
  { id: 1, label: 'Senior dog food', text: 'premium dog food for senior dogs' },
  { id: 2, label: 'Vermont candles', text: 'hand-poured candles from Vermont' },
]

const result: CampaignResult = {
  input_text: samples[0].text,
  budget_usd: 25000,
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
  publishers: [
    { publisher_id: 'p1', name: 'Pawline', fit: 0.88, factors: [], recommended: true, stretch: false, reason: '' },
    { publisher_id: 'p2', name: 'Skipped', fit: 0.1, factors: [], recommended: false, stretch: false, reason: '' },
  ],
  personas: [{ persona_id: 'a', name: 'Pet Parent', fit: 0.9, factors: [], stretch: false }],
  creatives: [],
  clarify: [],
  config: null,
}

beforeEach(() => {
  vi.mocked(getSamples).mockReset().mockResolvedValue(samples)
  vi.mocked(runCampaign).mockReset().mockResolvedValue(result)
})

describe('Landing', () => {
  it('prefills the textarea with sample #1 and shows default budget', async () => {
    render(<App />)
    const ta = await screen.findByLabelText('Describe your brand')
    await waitFor(() => expect(ta).toHaveValue(samples[0].text))
    expect(screen.getByLabelText('Monthly budget in USD')).toHaveValue('25,000')
  })

  it('shows placeholders in the reading panel before the first run', async () => {
    render(<App />)
    expect(await screen.findByText(/appears here after you build/i)).toBeInTheDocument()
  })

  it('chip click fills the textarea and runs the campaign with that sample text', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Vermont candles' }))
    expect(runCampaign).toHaveBeenCalledWith({ text: samples[1].text, budget_usd: 25000 })
    expect(await screen.findByRole('tab', { name: /publishers/i })).toBeInTheDocument()
  })

  it('Build campaign runs, switches to results, Back returns with the panel filled', async () => {
    const user = userEvent.setup()
    render(<App />)
    const ta = await screen.findByLabelText('Describe your brand')
    await waitFor(() => expect(ta).toHaveValue(samples[0].text))
    await user.click(screen.getByRole('button', { name: /build campaign/i }))
    expect(await screen.findByRole('tab', { name: /publishers/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /new campaign/i }))
    const panel = screen.getByLabelText('How we read your brand')
    expect(within(panel).getByText('Pawline')).toBeInTheDocument()
    expect(within(panel).getByText('Pet Parent')).toBeInTheDocument()
    expect(within(panel).getByText('Premium')).toBeInTheDocument()
    expect(within(panel).getByText(/enough to proceed/i)).toBeInTheDocument()
  })

  it('disables the button when the text is empty', async () => {
    const user = userEvent.setup()
    render(<App />)
    const ta = await screen.findByLabelText('Describe your brand')
    await waitFor(() => expect(ta).toHaveValue(samples[0].text))
    await user.clear(ta)
    expect(screen.getByRole('button', { name: /build campaign/i })).toBeDisabled()
  })

  it('disables the button when the budget is zero', async () => {
    const user = userEvent.setup()
    render(<App />)
    const ta = await screen.findByLabelText('Describe your brand')
    await waitFor(() => expect(ta).toHaveValue(samples[0].text))
    await user.clear(screen.getByLabelText('Monthly budget in USD'))
    expect(screen.getByRole('button', { name: /build campaign/i })).toBeDisabled()
  })

  it('disables the button and shows reading state while running', async () => {
    const user = userEvent.setup()
    let resolve!: (r: CampaignResult) => void
    vi.mocked(runCampaign).mockReturnValue(new Promise((r) => (resolve = r)))
    render(<App />)
    const ta = await screen.findByLabelText('Describe your brand')
    await waitFor(() => expect(ta).toHaveValue(samples[0].text))
    await user.click(screen.getByRole('button', { name: /build campaign/i }))
    const btn = await screen.findByRole('button', { name: /reading your brand/i })
    expect(btn).toBeDisabled()
    resolve(result)
    expect(await screen.findByRole('tab', { name: /publishers/i })).toBeInTheDocument()
  })

  it('renders a string-shaped error detail inline', async () => {
    const user = userEvent.setup()
    vi.mocked(runCampaign).mockRejectedValue(new ApiError(429, 'Too many requests, slow down'))
    render(<App />)
    await waitFor(() => expect(screen.getByLabelText('Describe your brand')).toHaveValue(samples[0].text))
    await user.click(screen.getByRole('button', { name: /build campaign/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many requests, slow down')
  })

  it('renders a list-shaped 422 detail inline (via real api layer)', async () => {
    const user = userEvent.setup()
    const actual = await vi.importActual<typeof import('./api')>('./api')
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({ detail: [{ loc: ['body', 'text'], msg: 'Text is too long', type: 'x' }] }),
      }),
    )
    vi.mocked(runCampaign).mockImplementation(actual.runCampaign)
    render(<App />)
    await waitFor(() => expect(screen.getByLabelText('Describe your brand')).toHaveValue(samples[0].text))
    await user.click(screen.getByRole('button', { name: /build campaign/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Text is too long')
    vi.unstubAllGlobals()
  })
})
