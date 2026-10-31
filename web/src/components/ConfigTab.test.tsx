import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { CampaignConfig, CampaignResult, Creative, PublisherScore } from '../types'
import ConfigTab from './ConfigTab'
import PersonasTab from './PersonasTab'
import PublishersTab from './PublishersTab'
import Results from './Results'

const config: CampaignConfig = {
  campaign_id: 'cmp_1',
  objective: 'conversions',
  conversion_event: 'subscription_start',
  budget: { monthly_usd: 25000, pacing: 'even', unallocated_usd: 1500, test_budget: true },
  bid_strategy: { type: 'target_cpa', target_usd: 42 },
  targeting: {
    age_range: [30, 60],
    gender: 'all',
    geo: ['US'],
    interests: ['pet'],
    personas: ['persona_001'],
  },
  line_items: [
    { publisher_id: 'pub_a', share: 0.41, budget_usd: 10250, creative_id: 'cr1' },
    { publisher_id: 'pub_b', share: 0.59, budget_usd: 14750, creative_id: null },
  ],
  frequency_cap: { impressions: 3, per_days: 7 },
  guardrails: { pause_if_cpa_over_x: 1.5, cpa_limit_usd: 63, min_impressions: 2000 },
  rationales: { bid_strategy: '65% of $64 order value' },
  decision_trace: { gate_impl: 'llm' },
}

const fac = (name: string, score: number) => ({ name, score, note: `${name} note text` })
const pub = (id: string, name: string, fit: number, recommended: boolean, extra = {}): PublisherScore => ({
  publisher_id: id,
  name,
  fit,
  factors: [fac('category', 0.9), fac('audience', 0.8), fac('income', 0.7), fac('aov', 0.6)],
  recommended,
  stretch: false,
  reason: `${name} reason`,
  ...extra,
})

describe('ConfigTab', () => {
  it('shows Formatted by default with $25,000, JSON on click, from the same object', async () => {
    const user = userEvent.setup()
    render(<ConfigTab config={config} />)
    expect(screen.getByText(/\$25,000/)).toBeInTheDocument()
    expect(screen.getByText(/Target CPA · \$42/)).toBeInTheDocument()
    expect(screen.getByText('Test budget')).toBeInTheDocument()
    expect(screen.getByText(/Unallocated \$1,500/)).toBeInTheDocument()
    expect(screen.getByText(/3 \/ user \/ 7 days/)).toBeInTheDocument()
    expect(screen.queryByText(/"bid_strategy"/)).toBeNull()
    await user.click(screen.getByRole('tab', { name: 'JSON' }))
    expect(screen.getAllByText(/"bid_strategy"/).length).toBeGreaterThan(0)
    expect(screen.getByText('25000')).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Formatted' }))
    expect(screen.getByText(/\$25,000/)).toBeInTheDocument()
  })

  it('shows a Pacing row with its rationale and marks a user-set budget', () => {
    const c = {
      ...config,
      budget: { ...config.budget, pacing: 'front_loaded' as const, source: 'user' as const, recommended_usd: 6000 },
      rationales: { ...config.rationales, pacing: 'Front-loaded: a small weak-fit test should learn fast' },
    }
    render(<ConfigTab config={c} />)
    expect(screen.getByText(/front loaded pacing/)).toBeInTheDocument()
    expect(screen.getByText('Front loaded')).toBeInTheDocument()
    expect(screen.getByText('Front-loaded: a small weak-fit test should learn fast')).toBeInTheDocument()
    expect(screen.getByText('Your budget')).toBeInTheDocument()
  })

  it('lists extra rotating creatives on a line item, tolerating their absence', () => {
    const c = {
      ...config,
      line_items: [
        { ...config.line_items[0], extra_creative_ids: ['cr2'] },
        config.line_items[1],
      ],
    }
    const mk = (id: string, persona: string): Creative => ({
      creative_id: id, persona_id: persona, publisher_id: 'pub_a', headline: 'h', body: 'b', cta: 'c', why: 'w', fact_violations: [],
    })
    render(
      <ConfigTab
        config={c}
        publishers={[pub('pub_a', 'Pawline', 0.8, true), pub('pub_b', 'Ruffco', 0.7, true)]}
        personas={[
          { persona_id: 'p1', name: 'Pet Parent', fit: 0.9, factors: [], stretch: false },
          { persona_id: 'p2', name: 'Busy Parent', fit: 0.8, factors: [], stretch: false },
        ]}
        creatives={[mk('cr1', 'p1'), mk('cr2', 'p2')]}
      />,
    )
    expect(screen.getByText('→ Pet Parent, Busy Parent', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('→ no creative', { exact: false })).toBeInTheDocument()
  })

  it('puts rationales in a title tooltip', () => {
    render(<ConfigTab config={config} />)
    expect(screen.getByTitle('65% of $64 order value')).toHaveTextContent('Bid strategy')
  })

  it('shows each rationale as a visible line under its row, snake_case humanised', () => {
    const withTargeting = {
      ...config,
      rationales: { ...config.rationales, targeting: '3 personas, interests pet_food, pet_health, ages 50-80' },
    }
    render(<ConfigTab config={withTargeting} />)
    expect(screen.getByText('65% of $64 order value')).toBeInTheDocument()
    expect(screen.getByText('3 personas, interests pet food, pet health, ages 50-80')).toBeInTheDocument()
    expect(screen.queryByText(/pet_food/)).toBeNull()
  })

  it('escapes markup from values in the JSON view', async () => {
    const user = userEvent.setup()
    const evil = { ...config, campaign_id: '<script>alert(1)</script>' }
    const { container } = render(<ConfigTab config={evil} />)
    await user.click(screen.getByRole('tab', { name: 'JSON' }))
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('pre')!.textContent).toContain('<script>alert(1)</script>')
  })

  it('Copy writes pretty JSON to the clipboard and shows Copied', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<ConfigTab config={config} />)
    await user.click(screen.getByRole('tab', { name: 'JSON' }))
    await user.click(screen.getByRole('button', { name: 'Copy' }))
    expect(writeText).toHaveBeenCalledWith(JSON.stringify(config, null, 2))
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
  })
})

describe('ConfigJson copy failure', () => {
  it('shows a failure message when the clipboard is unavailable', async () => {
    const user = userEvent.setup()
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    render(<ConfigTab config={config} />)
    await user.click(screen.getByRole('tab', { name: 'JSON' }))
    await user.click(screen.getByRole('button', { name: 'Copy' }))
    expect(await screen.findByRole('button', { name: /copy failed/i })).toBeInTheDocument()
  })
})

describe('Tabs a11y', () => {
  it('arrow keys move between tabs, with roving tabindex and panel linkage', async () => {
    const user = userEvent.setup()
    render(<ConfigTab config={config} />)
    const list = screen.getByRole('tablist', { name: 'Config view' })
    const [t1, t2] = within(list).getAllByRole('tab')
    expect(t1).toHaveAttribute('tabindex', '0')
    expect(t2).toHaveAttribute('tabindex', '-1')
    t1.focus()
    await user.keyboard('{ArrowRight}')
    expect(t2).toHaveAttribute('aria-selected', 'true')
    expect(t2).toHaveFocus()
    const panel = screen.getByRole('tabpanel')
    expect(panel).toHaveAttribute('aria-labelledby', t2.id)
    expect(t2).toHaveAttribute('aria-controls', panel.id)
    await user.keyboard('{ArrowLeft}')
    expect(t1).toHaveAttribute('aria-selected', 'true')
  })
})

describe('PublishersTab', () => {
  it('shows an empty state with no recommended publishers', () => {
    render(<PublishersTab publishers={[pub('x', 'Nope', 0.1, false)]} config={config} />)
    expect(screen.getByText(/no publisher cleared/i)).toBeInTheDocument()
  })

  const pubs = [
    pub('pub_a', 'Pawline', 0.88, true, { stretch: true }),
    pub('pub_b', 'Ruffco', 0.79, true),
    ...Array.from({ length: 6 }, (_, i) => pub(`x${i}`, `Excl${i}`, 0.1 + i * 0.05, false)),
  ]

  it('shows budget and share from the config line item, stretch badge, and Details toggle', async () => {
    const user = userEvent.setup()
    render(<PublishersTab publishers={pubs} config={config} />)
    const card = screen.getByRole('article', { name: 'Pawline' })
    expect(within(card).getByText('$10,250 · 41%')).toBeInTheDocument()
    expect(within(card).getByText('0.88')).toBeInTheDocument()
    expect(within(card).getByText('Stretch')).toBeInTheDocument()
    expect(within(card).getAllByTestId('factor-bar')).toHaveLength(4)
    expect(within(card).queryByText(/category note text/)).toBeNull()
    await user.click(within(card).getByRole('button', { name: /details/i }))
    expect(within(card).getByText(/category note text/)).toBeInTheDocument()
  })

  it('lists first 4 excluded by fit desc then Show N more', async () => {
    const user = userEvent.setup()
    render(<PublishersTab publishers={pubs} config={config} />)
    expect(screen.getByText('Excluded · 6')).toBeInTheDocument()
    let rows = screen.getAllByTestId('excluded')
    expect(rows).toHaveLength(4)
    expect(rows[0]).toHaveTextContent('Excl5')
    await user.click(screen.getByRole('button', { name: /show 2 more/i }))
    rows = screen.getAllByTestId('excluded')
    expect(rows).toHaveLength(6)
  })
})

describe('PersonasTab', () => {
  it('renders ad, stretch prefix and a fact-violation chip', () => {
    const creatives: Creative[] = [
      {
        creative_id: 'cr1',
        persona_id: 'persona_001',
        publisher_id: 'pub_a',
        headline: 'Read the label',
        body: 'Body copy',
        cta: 'See formula',
        why: 'Buys on evidence',
        fact_violations: ['claims "vet approved"'],
      },
    ]
    // underscores in `why` are shown as spaces (safety net)
    creatives[0].why = 'Leans on pet_health'
    render(
      <PersonasTab
        personas={[{ persona_id: 'persona_001', name: 'The Wellness Optimizer', fit: 0.58, factors: [], stretch: true }]}
        creatives={creatives}
        publishers={[pub('pub_a', 'Pawline', 0.8, true)]}
      />,
    )
    expect(screen.getByText('Sponsored · on Pawline')).toBeInTheDocument()
    expect(screen.getByText('Stretch:')).toBeInTheDocument()
    expect(screen.getByText(/Leans on pet health/)).toBeInTheDocument()
    expect(screen.getByText('science-backed claims')).toBeInTheDocument()
    expect(screen.getByText('Check: claims "vet approved"')).toBeInTheDocument()
  })
})

describe('Results', () => {
  const base = {
    input_text: 'dog food',
    budget_usd: 25000,
    message: 'Please say more',
    brief: null,
    gate: null,
    publishers: [],
    personas: [],
    creatives: [],
    clarify: [],
    config: null,
  }
  it('renders the clarify view with Back for non-proceed outcomes', async () => {
    const onBack = vi.fn()
    const user = userEvent.setup()
    render(<Results result={{ ...base, outcome: 'clarify' } as CampaignResult} onBack={onBack} />)
    expect(screen.getByText('We need a bit more before spending your budget.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /new campaign/i }))
    expect(onBack).toHaveBeenCalled()
  })
  it('proceed results open on step 1 of the stepper', () => {
    const r = {
      ...base,
      outcome: 'proceed',
      gate: { outcome: 'proceed', confidence: 0.9, threshold: 0.7, impl: 'llm', signals: {} },
      publishers: [pub('pub_a', 'Pawline', 0.88, true)],
    } as CampaignResult
    render(<Results result={r} onBack={() => {}} />)
    const steps = screen.getByRole('navigation', { name: 'Campaign steps' })
    expect(within(steps).getByRole('button', { name: /publishers & personas/i })).toHaveAttribute('aria-current', 'step')
    expect(screen.getByRole('article', { name: 'Pawline' })).toBeInTheDocument()
  })
})
