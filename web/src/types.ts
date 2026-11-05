// TypeScript mirror of app/models/. Keep field names and unions identical.

export type Outcome = 'proceed' | 'clarify' | 'out_of_scope' | 'no_signal' | 'weak_fit'
export type PriceTier = 'value' | 'mid' | 'premium' | 'luxury' | 'unknown'

export interface Brief {
  describes_business: boolean
  product: string | null
  audience_type: 'consumer' | 'business' | 'not_shoppable' | 'unclear'
  categories: string[]
  adjacent_categories: string[]
  conflicts: string[]
  price_usd: number | null
  price_tier: PriceTier
  business_model: 'subscription' | 'one_off' | 'unknown'
  age_min: number | null
  age_max: number | null
  gender_skew: 'female' | 'male' | 'balanced' | 'unknown'
  facts: string[]
  unknowns: string[]
  self_confidence: number
}

export interface GateResult {
  outcome: Outcome
  confidence: number
  threshold: number
}

export interface Factor {
  name: string
  score: number
  note: string
}

export interface PublisherScore {
  publisher_id: string
  name: string
  fit: number
  factors: Factor[]
  recommended: boolean
  stretch: boolean
  reason: string
}

export interface PersonaScore {
  persona_id: string
  name: string
  fit: number
  factors: Factor[]
  stretch: boolean
}

export interface Creative {
  /** One ad per persona, so the persona id is the ad's id. */
  persona_id: string
  publisher_id: string
  headline: string
  body: string
  cta: string
  why: string
  fact_violations: string[]
}

export interface ClarifyQuestion {
  question: string
  options: string[]
}

export interface LineItem {
  publisher_id: string
  share: number
  budget_usd: number
  /** What 1,000 impressions cost on this publisher (by audience income). */
  cpm_usd: number
  est_impressions: number
  /** Persona ids of the ads served here: the first is primary, the rest rotate. */
  ads: string[]
}

export type Pacing = 'front_loaded' | 'even' | 'accelerated'

export interface ConfigBudget {
  monthly_usd: number
  recommended_usd: number
  source: 'recommended' | 'user'
  pacing: Pacing
  est_impressions: number
  est_conversions: number
  est_revenue_usd: number
  est_roas: number
}

export interface CampaignConfig {
  campaign_id: string
  objective: 'conversions'
  conversion_event: 'purchase' | 'subscription_start'
  budget: ConfigBudget
  bid_strategy: Record<string, unknown>
  targeting: Record<string, unknown>
  line_items: LineItem[]
  frequency_cap: Record<string, unknown>
  guardrails: Record<string, unknown>
  /** One line per field: objective, bid_strategy, budget, pacing, frequency_cap, ... */
  rationales: Record<string, string>
}

export interface CampaignResult {
  /** The advertiser's text, with any clarify answers appended. */
  input_text: string
  /** The user's budget, if they gave one; kept for step 4. */
  budget_usd: number | null
  outcome: Outcome
  message: string | null
  brief: Brief | null
  gate: GateResult | null
  publishers: PublisherScore[]
  personas: PersonaScore[]
  clarify: ClarifyQuestion[]
  /** What a note changed, and what it couldn't apply. */
  notes: string[]
}

export interface Sample {
  id: number
  label: string
  text: string
}

export interface CampaignRequest {
  text: string
  /** Omit (or null) to use the recommended budget. */
  budget_usd?: number | null
  answers?: Record<string, string>
  /** Free text that updates step 1; sent with the brief to reuse, so the text isn't read again. */
  note?: string
  brief?: Brief
}

/** Step 1's result sent back to steps 3 and 4, with an optional note for that step. */
