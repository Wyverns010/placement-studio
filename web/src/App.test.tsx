import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CampaignResult, Sample } from './types'

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api')
  return { ...actual, getSamples: vi.fn(), runCampaign: vi.fn(), streamCampaign: vi.fn(), createCreatives: vi.fn() }
})
import { ApiError, createCreatives, getSamples, runCampaign, streamCampaign } from './api'
import type { StageEvent } from './types'
import App from './App'

const samples: Sample[] = [
  { id: 1, label: 'Senior dog food', text: 'premium dog food for senior dogs' },
  { id: 2, label: 'Vermont candles', text: 'hand-poured candles from Vermont' },
]

const result: CampaignResult = {
  input_text: samples[0].text,
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
  // Default stream: behaves like the POST fallback (one `done` or `error`), so tests that
  // mock runCampaign keep working. Streaming-specific tests override this.
  vi.mocked(streamCampaign)
    .mockReset()
    .mockImplementation((req, onEvent) => {
      let off = false
      runCampaign(req)
        .then((r) => !off && onEvent({ stage: 'done', data: r as unknown as Record<string, unknown> }))
        .catch((e) => !off && onEvent({ stage: 'error', data: { message: e.message } }))
      return () => {
        off = true
      }
    })
  setReducedMotion(true)
})

function setReducedMotion(reduce: boolean) {
  window.matchMedia = ((q: string) => ({
    matches: reduce && q.includes('reduce'),
    media: q,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia
}

describe('Landing', () => {
  it('prefills the textarea with sample #1 and leaves the budget blank (recommended)', async () => {
    render(<App />)
    const ta = await screen.findByLabelText('Describe your brand')
    await waitFor(() => expect(ta).toHaveValue(samples[0].text))
    expect(screen.getByLabelText('Monthly budget in USD')).toHaveValue('')
    expect(screen.getByText('Leave blank to use our recommendation')).toBeInTheDocument()
  })

  it('sends a typed budget with the run', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitFor(() => expect(screen.getByLabelText('Describe your brand')).toHaveValue(samples[0].text))
    await user.type(screen.getByLabelText('Monthly budget in USD'), '$12,000.00')
    await user.click(screen.getByRole('button', { name: /build campaign/i }))
    expect(runCampaign).toHaveBeenCalledWith({ text: samples[0].text, budget_usd: 12000 })
  })

  it('shows placeholders in the reading panel before the first run', async () => {
    render(<App />)
    expect(await screen.findByText(/appears here after you build/i)).toBeInTheDocument()
  })

  it('chip click fills the textarea and runs the campaign with that sample text', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Vermont candles' }))
    expect(runCampaign).toHaveBeenCalledWith({ text: samples[1].text })
    expect(await screen.findByRole('navigation', { name: 'Campaign steps' })).toBeInTheDocument()
  })

  it('Build campaign runs, switches to results, Back returns with the panel filled', async () => {
    const user = userEvent.setup()
    render(<App />)
    const ta = await screen.findByLabelText('Describe your brand')
    await waitFor(() => expect(ta).toHaveValue(samples[0].text))
    await user.click(screen.getByRole('button', { name: /build campaign/i }))
    expect(await screen.findByRole('navigation', { name: 'Campaign steps' })).toBeInTheDocument()
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

  it('disables the button and explains the range for an out-of-range budget', async () => {
    const user = userEvent.setup()
    render(<App />)
    const ta = await screen.findByLabelText('Describe your brand')
    await waitFor(() => expect(ta).toHaveValue(samples[0].text))
    const input = screen.getByLabelText('Monthly budget in USD')
    await user.type(input, '0')
    expect(input).toHaveValue('0')
    expect(screen.getByRole('button', { name: /build campaign/i })).toBeDisabled()
    expect(screen.getByText(/between \$500 and \$5,000,000/)).toBeInTheDocument()
    await user.clear(input)
    expect(screen.getByRole('button', { name: /build campaign/i })).toBeEnabled()
    await user.type(input, '1e3')
    expect(screen.getByRole('button', { name: /build campaign/i })).toBeDisabled()
    await user.clear(input)
    await user.type(input, '999999999999999999999')
    expect(screen.getByText(/between \$500 and \$5,000,000/)).toBeInTheDocument()
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
    expect(await screen.findByRole('navigation', { name: 'Campaign steps' })).toBeInTheDocument()
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

describe('Outcome states', () => {
  const clarify: CampaignResult = {
    ...result,
    outcome: 'clarify',
    gate: { outcome: 'clarify', confidence: 0.31, threshold: 0.7, impl: 'llm', signals: {} },
    clarify: [{ question: 'What is the product?', options: ['Physical product'] }],
    publishers: [{ ...result.publishers[0], recommended: false }],
  }

  async function toClarify(user: ReturnType<typeof userEvent.setup>) {
    vi.mocked(runCampaign).mockResolvedValueOnce(clarify)
    render(<App />)
    const ta = await screen.findByLabelText('Describe your brand')
    await waitFor(() => expect(ta).toHaveValue(samples[0].text))
    await user.click(screen.getByRole('button', { name: /build campaign/i }))
    await screen.findByRole('button', { name: /rebuild campaign/i })
  }

  it('Rebuild re-runs with the original text, budget and answers, and replaces the result', async () => {
    const user = userEvent.setup()
    await toClarify(user)
    await user.click(screen.getByRole('button', { name: 'Physical product' }))
    await user.click(screen.getByRole('button', { name: /rebuild campaign/i }))
    expect(runCampaign).toHaveBeenLastCalledWith({
      text: samples[0].text,
      answers: { 'What is the product?': 'Physical product' },
    })
    expect(await screen.findByRole('navigation', { name: 'Campaign steps' })).toBeInTheDocument()
  })

  it('keeps the typed text in the header and carries earlier answers into the next rebuild', async () => {
    const user = userEvent.setup()
    await toClarify(user)
    vi.mocked(runCampaign).mockResolvedValueOnce({
      ...clarify,
      input_text: `${samples[0].text}\n\nAdditional details:\n- What is the product?: Physical product`,
      clarify: [{ question: 'Which category?', options: ['Home'] }],
    })
    await user.click(screen.getByRole('button', { name: 'Physical product' }))
    await user.click(screen.getByRole('button', { name: /rebuild campaign/i }))
    await user.click(await screen.findByRole('button', { name: 'Home' }))
    expect(screen.getByText(`“${samples[0].text}”`)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /rebuild campaign/i }))
    expect(runCampaign).toHaveBeenLastCalledWith({
      text: samples[0].text,
      answers: { 'What is the product?': 'Physical product', 'Which category?': 'Home' },
    })
  })

  it('a failed rebuild shows a red alert, no spinner, and Try a sample returns to landing', async () => {
    const user = userEvent.setup()
    await toClarify(user)
    vi.mocked(runCampaign).mockRejectedValueOnce(new ApiError(500, 'Boom'))
    await user.click(screen.getByRole('button', { name: 'Physical product' }))
    await user.click(screen.getByRole('button', { name: /rebuild campaign/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Boom')
    expect(screen.getByRole('button', { name: /rebuild campaign/i })).toBeEnabled()
    expect(screen.queryByText(/rebuilding/i)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try a sample' }))
    expect(await screen.findByLabelText('Describe your brand')).toBeInTheDocument()
  })

  it('out_of_scope shows the message, excluded list with Show more, and sample chips that run', async () => {
    const user = userEvent.setup()
    const pubs = Array.from({ length: 8 }, (_, i) => ({
      ...result.publishers[1],
      publisher_id: `x${i}`,
      name: `Pub ${i}`,
      fit: 0.5 - i * 0.01,
      reason: 'B2B is not shoppable',
    }))
    vi.mocked(runCampaign).mockResolvedValueOnce({
      ...result,
      outcome: 'out_of_scope',
      message: 'We place consumer shopping ads only.',
      publishers: pubs,
      personas: [],
    })
    render(<App />)
    await waitFor(() => expect(screen.getByLabelText('Describe your brand')).toHaveValue(samples[0].text))
    await user.click(screen.getByRole('button', { name: /build campaign/i }))
    expect(await screen.findByText('We place consumer shopping ads only.')).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Campaign steps' })).not.toBeInTheDocument()
    expect(screen.getAllByTestId('excluded')).toHaveLength(6)
    await user.click(screen.getByRole('button', { name: /show 2 more/i }))
    expect(screen.getAllByTestId('excluded')).toHaveLength(8)
    await user.click(screen.getByRole('button', { name: 'Vermont candles' }))
    expect(runCampaign).toHaveBeenLastCalledWith({ text: samples[1].text })
  })

  it('a failing sample run from out_of_scope shows the red alert, no spinner; chips disabled while running', async () => {
    const user = userEvent.setup()
    vi.mocked(runCampaign).mockResolvedValueOnce({ ...result, outcome: 'out_of_scope', message: 'No.', publishers: [], personas: [] })
    render(<App />)
    await waitFor(() => expect(screen.getByLabelText('Describe your brand')).toHaveValue(samples[0].text))
    await user.click(screen.getByRole('button', { name: /build campaign/i }))
    await screen.findByText('No.')
    let reject!: (e: Error) => void
    vi.mocked(runCampaign).mockReturnValueOnce(new Promise((_, r) => (reject = r)))
    await user.click(screen.getByRole('button', { name: 'Vermont candles' }))
    expect(screen.getByRole('button', { name: 'Vermont candles' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Senior dog food' })).toBeDisabled()
    reject(new ApiError(500, 'Sample failed'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Sample failed')
    expect(screen.queryByText(/reading your brand/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Vermont candles' })).toBeEnabled()
  })

  it('ignores a late result after going back home', async () => {
    const user = userEvent.setup()
    await toClarify(user)
    let resolve!: (r: CampaignResult) => void
    vi.mocked(runCampaign).mockReturnValueOnce(new Promise((r) => (resolve = r)))
    await user.click(screen.getByRole('button', { name: 'Physical product' }))
    await user.click(screen.getByRole('button', { name: /rebuild campaign/i }))
    await user.click(screen.getByRole('button', { name: /new campaign/i }))
    resolve(result)
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.getByLabelText('Describe your brand')).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Campaign steps' })).not.toBeInTheDocument()
  })

  it('a re-answered key at the cap counts as newest', async () => {
    const user = userEvent.setup()
    await toClarify(user)
    const qs = ['q1', 'q2', 'q3', 'q4', 'q5']
    for (let i = 0; i < 5; i++) {
      vi.mocked(runCampaign).mockResolvedValueOnce({
        ...clarify,
        clarify: [{ question: qs[i], options: ['a'] }, ...(i === 4 ? [{ question: 'What is the product?', options: ['Physical product'] }] : [])],
      })
    }
    // first rebuild answers the original question, then q1..q4 in turn
    await user.click(screen.getByRole('button', { name: 'Physical product' }))
    await user.click(screen.getByRole('button', { name: /rebuild campaign/i }))
    for (let i = 0; i < 4; i++) {
      await user.click(await screen.findByRole('button', { name: 'a' }))
      await user.click(screen.getByRole('button', { name: /rebuild campaign/i }))
    }
    // now asked q5 and the original question again: answer both
    await user.click(await screen.findByRole('button', { name: 'Physical product' }))
    await user.click(screen.getByRole('button', { name: 'a' }))
    await user.click(screen.getByRole('button', { name: /rebuild campaign/i }))
    const last = vi.mocked(runCampaign).mock.calls.at(-1)![0].answers!
    // oldest untouched answer (q1) is dropped; the re-answered key is kept as newest
    expect(Object.keys(last)).toEqual(['q2', 'q3', 'q4', 'What is the product?', 'q5'])
  })

  it('weak_fit keeps the stepper and adds the weak-fit banner', async () => {
    const user = userEvent.setup()
    vi.mocked(runCampaign).mockResolvedValueOnce({
      ...result,
      outcome: 'weak_fit',
      message: 'Few publishers match this closely.',
    })
    render(<App />)
    await waitFor(() => expect(screen.getByLabelText('Describe your brand')).toHaveValue(samples[0].text))
    await user.click(screen.getByRole('button', { name: /build campaign/i }))
    expect(await screen.findByText('Few publishers match this closely.')).toBeInTheDocument()
    expect(screen.getByText('Weak fit — treat this as a test.')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Campaign steps' })).toBeInTheDocument()
    // the gate card judges the brief: still "Clear", as a percentage
    expect(screen.getByText('Brief clarity')).toBeInTheDocument()
    expect(screen.getByText('Clear')).toBeInTheDocument()
    expect(screen.getByText(/% — needs \d+%/)).toBeInTheDocument()
  })

  it('stage 2 gets the API input_text (answers appended); a 403 Run it again re-runs stage 1', async () => {
    const user = userEvent.setup()
    await toClarify(user)
    const echoed = `${samples[0].text}\n\nAdditional details:\n- What is the product?: Physical product`
    vi.mocked(runCampaign).mockResolvedValueOnce({ ...result, input_text: echoed, stage_token: 't1' })
    await user.click(screen.getByRole('button', { name: 'Physical product' }))
    await user.click(screen.getByRole('button', { name: /rebuild campaign/i }))
    expect(await screen.findByText(`“${samples[0].text}”`)).toBeInTheDocument()
    vi.mocked(createCreatives).mockRejectedValueOnce(new ApiError(403, 'This campaign changed or expired — run it again.'))
    await user.click(screen.getByRole('button', { name: /write ads for these publishers/i }))
    expect(vi.mocked(createCreatives).mock.calls[0][0]).toMatchObject({ input_text: echoed, stage_token: 't1' })
    await user.click(await screen.findByRole('button', { name: /run it again/i }))
    expect(runCampaign).toHaveBeenLastCalledWith({
      text: samples[0].text,
      answers: { 'What is the product?': 'Physical product' },
    })
    // the fresh result starts again at step 1 with no stale error
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: /write ads for these publishers/i })).toBeEnabled()
  })
})

describe('Live streaming', () => {
  let emit!: (e: StageEvent) => void
  const cancel = vi.fn()
  beforeEach(() => {
    cancel.mockReset()
    setReducedMotion(false)
    vi.mocked(streamCampaign).mockReset().mockImplementation((_req, onEvent) => {
      emit = onEvent
      return cancel
    })
  })

  async function start(user: ReturnType<typeof userEvent.setup>) {
    render(<App />)
    await waitFor(() => expect(screen.getByLabelText('Describe your brand')).toHaveValue(samples[0].text))
    await user.click(screen.getByRole('button', { name: /build campaign/i }))
  }
  const panel = () => within(screen.getByRole('complementary', { name: /how we read your brand/i }))

  it('fills lanes as stages arrive, then shows results after the 600 ms hold', async () => {
    const user = userEvent.setup()
    await start(user)
    expect(panel().getAllByLabelText('working')).toHaveLength(4)

    act(() => emit({ stage: 'understood', data: result.brief as unknown as Record<string, unknown> }))
    expect(panel().getByText('Pet')).toBeInTheDocument()
    expect(panel().getAllByLabelText('working')).toHaveLength(3)

    act(() => emit({ stage: 'gate', data: result.gate as unknown as Record<string, unknown> }))
    expect(panel().getByText(/91% vs\. needed 70%/)).toBeInTheDocument()
    expect(panel().getByText('enough to proceed')).toBeInTheDocument()

    act(() =>
      emit({
        stage: 'publishers',
        data: {
          recommended: ['p1'],
          top: [
            { id: 'p1', name: 'Pawline', fit: 0.88 },
            { id: 'p2', name: 'Skipped', fit: 0.1 },
          ],
        },
      }),
    )
    expect(panel().getByText('Pawline')).toBeInTheDocument()
    expect(panel().queryByText('Skipped')).not.toBeInTheDocument()

    act(() => emit({ stage: 'personas', data: { selected: [{ id: 'a', name: 'Pet Parent', fit: 0.9, stretch: false }] } }))
    expect(panel().getByText('Pet Parent')).toBeInTheDocument()
    expect(panel().queryAllByLabelText('working')).toHaveLength(0)

    act(() => emit({ stage: 'done', data: result as unknown as Record<string, unknown> }))
    // Panel stays filled during the hold...
    expect(screen.queryByRole('navigation', { name: 'Campaign steps' })).not.toBeInTheDocument()
    expect(panel().getByText('Pawline')).toBeInTheDocument()
    // ...then switches to results.
    expect(await screen.findByRole('navigation', { name: 'Campaign steps' }, { timeout: 2000 })).toBeInTheDocument()
  })

  it('switches to results immediately under prefers-reduced-motion', async () => {
    setReducedMotion(true)
    const user = userEvent.setup()
    await start(user)
    act(() => emit({ stage: 'done', data: result as unknown as Record<string, unknown> }))
    expect(screen.getByRole('navigation', { name: 'Campaign steps' })).toBeInTheDocument()
  })

  it('an error event shows the error banner and stops running', async () => {
    const user = userEvent.setup()
    await start(user)
    act(() => emit({ stage: 'error', data: { message: 'The AI service is taking too long — try again or pick a sample.' } }))
    expect(screen.getByRole('alert')).toHaveTextContent('taking too long')
    expect(screen.getByRole('button', { name: /build campaign/i })).toBeEnabled()
  })

  it('goHome cancels the stream and ignores late events', async () => {
    const user = userEvent.setup()
    await start(user)
    await user.click(screen.getByRole('button', { name: /placement studio home/i }))
    expect(cancel).toHaveBeenCalled()
    act(() => emit({ stage: 'done', data: result as unknown as Record<string, unknown> }))
    expect(screen.queryByRole('navigation', { name: 'Campaign steps' })).not.toBeInTheDocument()
  })

  it('unmount cancels the stream', async () => {
    const user = userEvent.setup()
    const { unmount } = render(<App />)
    await waitFor(() => expect(screen.getByLabelText('Describe your brand')).toHaveValue(samples[0].text))
    await user.click(screen.getByRole('button', { name: /build campaign/i }))
    unmount()
    expect(cancel).toHaveBeenCalled()
  })
})
