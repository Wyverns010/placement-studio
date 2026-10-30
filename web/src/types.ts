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
}

export interface CampaignConfig {
  campaign_id: string
  objective: 'conversions'
  conversion_event: 'purchase' | 'subscription_start'
  budget: Record<string, unknown>
  bid_strategy: Record<string, unknown>
  targeting: Record<string, unknown>
  line_items: LineItem[]
  frequency_cap: Record<string, unknown>
  guardrails: Record<string, unknown>
  rationales: Record<string, string>
  decision_trace: Record<string, unknown>
}

export interface CampaignResult {
  input_text: string
  budget_usd: number
  outcome: Outcome
  message: string | null
  brief: Brief | null
  gate: GateResult | null
  publishers: PublisherScore[]
  personas: PersonaScore[]
  creatives: Creative[]
  clarify: ClarifyQuestion[]
  config: CampaignConfig | null
}

export type StageName =
  | 'understood'
  | 'gate'
  | 'publishers'
  | 'personas'
  | 'creatives'
  | 'config'
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
  budget_usd: number
  answers?: Record<string, string>
}
