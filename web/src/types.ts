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
  impl: 'llm'
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
  /** What 1,000 impressions cost on this publisher (by audience income). */
  cpm_usd?: number
  est_impressions?: number
}

export type Pacing = 'front_loaded' | 'even' | 'accelerated'

export interface ConfigBudget {
  monthly_usd: number
  recommended_usd: number
  source: 'recommended' | 'user'
  pacing: Pacing
  unallocated_usd: number
  test_budget: boolean
  /** Conversions per line item per month (learning conversions per week x weeks). */
  conversions_goal?: number
  est_impressions?: number
  est_conversions?: number
  est_revenue_usd?: number
  est_roas?: number
  /** What the target CPA needs per 1,000 impressions; cpa_is_stretch when above the usual rate. */
  conversions_per_1k?: number
  cpa_is_stretch?: boolean
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
  /** Step-agent extras (outside the signed token): how this result was produced. */
  mode?: AgentMode
  agent_trace?: AgentTraceEntry[]
  agent_notes?: string[]
}

export type AgentMode = 'agent' | 'fallback' | 'code'

/** One tool call by a step agent. */
export interface AgentTraceEntry {
  agent: string
  tool: string
  args_summary?: string
  result_summary?: string
  ms?: number
}

/** What a step agent did (stage 1 result, /api/creatives, /api/config responses). */
export interface StepMeta {
  mode?: AgentMode
  agent_trace?: AgentTraceEntry[]
  agent_notes?: string[]
}

/** Longest steer the backend accepts (`agents.steer_max_chars`). */
export const STEER_MAX = 300

export type StageName =
  | 'agent'
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
  /** Optional free-text note for the strategist agent (≤ 300 chars). */
  steer?: string
}

/** Stage payloads received so far while a live run streams in. */
export interface StreamPartial {
  understood?: Brief
  gate?: GateResult
  publishers?: { recommended: string[]; top: { id: string; name: string; fit: number }[] }
  personas?: { selected: { id: string; name: string; fit: number; stretch: boolean }[] }
  /** Agent tool calls received so far (SSE `agent` events). */
  agent?: AgentTraceEntry[]
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
  /** Optional free-text note for the step's agent (≤ 300 chars); sent only when set. */
  steer?: string
}

export interface RegeneratePayload extends StagePayload {
  creatives: Creative[]
}

export interface ConfigPayload extends StagePayload {
  creatives: Creative[]
}
