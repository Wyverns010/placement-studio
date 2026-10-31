// TypeScript mirror of app/models.py. Keep field names and unions identical.

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
  impl: 'llm' | 'laya'
  signals: Record<string, number | string>
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
  creative_id: string
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
  creative_id: string | null
  /** More ads rotating on this line item (when personas outnumber publishers); may be absent. */
  extra_creative_ids?: string[]
}

export type Pacing = 'front_loaded' | 'even' | 'accelerated'

export interface ConfigBudget {
  monthly_usd: number
  recommended_usd: number
  source: 'recommended' | 'user'
  pacing: Pacing
  unallocated_usd: number
  test_budget: boolean
}

export interface CampaignConfig {
  campaign_id: string
  objective: 'conversions'
  conversion_event: 'purchase' | 'subscription_start'
  /** Typed loosely (the backend model is a dict); read fields defensively. */
  budget: Partial<ConfigBudget> & Record<string, unknown>
  bid_strategy: Record<string, unknown>
  targeting: Record<string, unknown>
  line_items: LineItem[]
  frequency_cap: Record<string, unknown>
  guardrails: Record<string, unknown>
  /** One line per field: objective, bid_strategy, budget, pacing, frequency_cap, ... */
  rationales: Record<string, string>
  decision_trace: Record<string, unknown>
}

export interface CampaignResult {
  input_text: string
  /** The user's budget, if they gave one; echoed so it can be passed to stage 3. */
  budget_usd: number | null
  outcome: Outcome
  message: string | null
  brief: Brief | null
  gate: GateResult | null
  publishers: PublisherScore[]
  personas: PersonaScore[]
  creatives: Creative[]
  clarify: ClarifyQuestion[]
  config: CampaignConfig | null
  /** Signs the stage-1 result; sent back with every stage-2/3 request (403 if it changed or expired). */
  stage_token?: string | null
}

export type StageName =
  | 'understood'
  | 'gate'
  | 'publishers'
  | 'personas'
  | 'done'
  | 'error'

export interface StageEvent {
  stage: StageName
  data: Record<string, unknown>
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
}

/** Stage payloads received so far while a live run streams in. */
export interface StreamPartial {
  understood?: Brief
  gate?: GateResult
  publishers?: { recommended: string[]; top: { id: string; name: string; fit: number }[] }
  personas?: { selected: { id: string; name: string; fit: number; stretch: boolean }[] }
  done?: true
}

/** What stage 1 returned, sent back unchanged (with its stage_token) to stages 2 and 3. */
export interface StagePayload {
  stage_token?: string | null
  input_text: string
  brief: Brief
  gate: GateResult
  publishers: PublisherScore[]
  personas: PersonaScore[]
}

export interface RegeneratePayload extends StagePayload {
  creatives: Creative[]
}

export interface ConfigPayload extends StagePayload {
  creatives: Creative[]
}
