import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { CampaignResult } from '../types'
import ClarifyView from './ClarifyView'

const base: CampaignResult = {
  input_text: 'A new kind of thing for moms',
  budget_usd: 25000,
  outcome: 'clarify',
  message: null,
  brief: null,
  gate: { outcome: 'clarify', confidence: 0.31, threshold: 0.7, impl: 'llm', signals: {} },
  publishers: [
    { publisher_id: 'a', name: 'Kitchenly', fit: 0.42, factors: [], recommended: false, stretch: false, reason: '' },
    { publisher_id: 'b', name: 'Swiftcart', fit: 0.36, factors: [], recommended: false, stretch: false, reason: '' },
    { publisher_id: 'c', name: 'Everbody', fit: 0.33, factors: [], recommended: false, stretch: false, reason: '' },
    { publisher_id: 'd', name: 'Lowfit', fit: 0.1, factors: [], recommended: false, stretch: false, reason: '' },
  ],
  personas: [{ persona_id: 'p', name: 'Busy Parent', fit: 0.5, factors: [], stretch: false }],
  creatives: [],
  clarify: [
    { question: 'What is the product?', options: ['Physical product', 'App / service'] },
    { question: 'Roughly what does it cost?', options: ['Under $30', '$30–100'] },
  ],
  config: null,
}

function setup(over: Partial<CampaignResult> = {}, props: { rebuilding?: boolean } = {}) {
  const onRebuild = vi.fn()
  render(<ClarifyView result={{ ...base, ...over }} onRebuild={onRebuild} {...props} />)
  return { onRebuild, user: userEvent.setup() }
}

describe('ClarifyView', () => {
  it('humanises the best-guess category chip', () => {
    const brief = {
      describes_business: true, product: 'Kit', audience_type: 'consumer', categories: ['pet_food'],
      adjacent_categories: [], conflicts: [], price_usd: null, price_tier: 'unknown',
      business_model: 'unknown', age_min: null, age_max: null, gender_skew: 'unknown', facts: [],
      unknowns: [], self_confidence: 0.4,
    } as unknown as CampaignResult['brief']
    setup({ brief })
    expect(screen.getByText('Category: Pet food')).toBeInTheDocument()
    expect(screen.queryByText(/pet_food/)).toBeNull()
  })

  it('Rebuild is disabled until a question is answered', async () => {
    const { user, onRebuild } = setup()
    const btn = screen.getByRole('button', { name: /rebuild campaign/i })
    expect(btn).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Physical product' }))
    expect(btn).toBeEnabled()
    await user.click(btn)
    expect(onRebuild).toHaveBeenCalledWith({ 'What is the product?': 'Physical product' })
  })

  it('chips are single-select per question', async () => {
    const { user, onRebuild } = setup()
    await user.click(screen.getByRole('button', { name: 'Physical product' }))
    await user.click(screen.getByRole('button', { name: 'App / service' }))
    await user.click(screen.getByRole('button', { name: 'Under $30' }))
    await user.click(screen.getByRole('button', { name: /rebuild campaign/i }))
    expect(onRebuild).toHaveBeenCalledWith({
      'What is the product?': 'App / service',
      'Roughly what does it cost?': 'Under $30',
    })
  })

  it('"Other…" reveals a free-text input capped at 200 chars', async () => {
    const { user, onRebuild } = setup()
    await user.click(screen.getAllByRole('button', { name: 'Other…' })[0])
    const input = screen.getByLabelText(/your answer: what is the product/i)
    expect(input).toHaveAttribute('maxlength', '200')
    await user.type(input, 'A baby sleep gadget')
    await user.click(screen.getByRole('button', { name: /rebuild campaign/i }))
    expect(onRebuild).toHaveBeenCalledWith({ 'What is the product?': 'A baby sleep gadget' })
  })

  it('drops backend "Other" options so only one Other… chip shows', () => {
    setup({ clarify: [{ question: 'Q?', options: ['A', 'Other'] }] })
    expect(screen.queryByRole('button', { name: 'Other' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Other…' })).toHaveLength(1)
  })

  it('de-dupes only whole Other-style options', () => {
    setup({
      clarify: [
        { question: 'Q?', options: ['Other', 'Other (please specify)', 'Something else', 'Other brands', 'Others', 'Otherwise'] },
      ],
    })
    for (const n of ['Other', 'Other (please specify)', 'Something else'])
      expect(screen.queryByRole('button', { name: n })).not.toBeInTheDocument()
    for (const n of ['Other brands', 'Others', 'Otherwise'])
      expect(screen.getByRole('button', { name: n })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Other…' })).toHaveLength(1)
  })

  it('empty Other text does not count as an answer', async () => {
    const { user } = setup()
    await user.click(screen.getAllByRole('button', { name: 'Other…' })[0])
    expect(screen.getByRole('button', { name: /rebuild campaign/i })).toBeDisabled()
  })

  it('clarify shows the faded best-guess card with top 3 publishers', () => {
    setup()
    expect(screen.getByText('We need a bit more before spending your budget.')).toBeInTheDocument()
    const card = screen.getByLabelText('Best guess so far')
    expect(card).toHaveTextContent('low confidence — not launchable')
    expect(card).toHaveTextContent('Kitchenly')
    expect(card).toHaveTextContent('Everbody')
    expect(card).not.toHaveTextContent('Lowfit')
    expect(card).toHaveTextContent('Busy Parent')
  })

  it('no_signal has no best-guess card', () => {
    setup({
      outcome: 'no_signal',
      message: 'Nothing to go on yet — tell us a little about what you sell.',
      publishers: [],
      personas: [],
    })
    expect(screen.getByText('Nothing to go on yet.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Best guess so far')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Physical product' })).toBeInTheDocument()
  })

  it('shows a busy button while rebuilding', () => {
    setup({}, { rebuilding: true })
    expect(screen.getByRole('button', { name: /rebuilding/i })).toBeDisabled()
  })
})
