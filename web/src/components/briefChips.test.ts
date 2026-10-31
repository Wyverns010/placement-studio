import { describe, expect, it } from 'vitest'
import { briefChips } from './ReadingPanel'
import type { Brief } from '../types'

describe('briefChips', () => {
  it('shows Subscription once when it is both a category and the business model', () => {
    const b = { categories: ['pet_food', 'subscription'], price_tier: 'premium', business_model: 'subscription' } as unknown as Brief
    const chips = briefChips(b)
    expect(chips.filter((c) => c === 'Subscription')).toHaveLength(1)
  })
})
