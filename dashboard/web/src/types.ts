export type Ci = [number, number]

export interface Metrics {
  n_trials: number
  n_scenarios?: number
  k?: number
  success_rate?: number
  success_ci95?: Ci
  policy_violation_rate?: number
  policy_attempt_rate?: number
  tool_error_rate?: number
  error_rate?: number
  avg_turns?: number
  latency_p50_ms?: number
  latency_p95_ms?: number
  cost_per_conversation_usd?: number
  cost_per_success_usd?: number | null
  total_agent_cost_usd?: number
  [key: string]: unknown
}

export interface Summary {
  overall: Metrics
  by_category: Record<string, Metrics>
}

export interface RunRow {
  id: string
  created_at: string
  environment: string
  label: string
  agent_type: string
  model: string | null
  prompt_version: string | null
  tool_descriptions: string | null
  retrieval: boolean | string | null
  injection_defense: boolean | string | null
  temperature: number | null
  trials_per_scenario: number | null
  scenario_set: Record<string, unknown>
  n_trials: number | null
  success_rate: number | null
  success_ci95: Ci | null
  pass_hat_k: number | null
  k: number
  violation_rate: number | null
  attempt_rate: number | null
  cost_per_conversation: number | null
  cost_per_success: number | null
  spend: Record<string, number> | null
  git_sha: string | null
}

export interface ScenarioRow {
  scenario_id: string
  category: string
  trials: number
  successes: number
  violations: number
  failed_checks: string[]
}

export interface RunDetail {
  run: RunRow
  config: Record<string, unknown>
  summary: Summary
  scenarios: ScenarioRow[]
  aborted: string | null
}

export interface TranscriptEvent {
  kind: 'user' | 'assistant' | 'tool_call' | 'tool_result' | 'system' | 'error'
  turn: number
  content: string | null
  tool: string | null
  arguments: Record<string, unknown> | null
  result: unknown
  ok: boolean | null
  error_kind: string | null
  rule: string | null
  t_ms: number
}

export interface CheckResult {
  name: string
  type: string
  kind: 'final_state' | 'tool_call' | 'policy' | 'transcript' | 'judge'
  passed: boolean
  required: boolean
  detail: string
  reasoning: string | null
}

export interface RuleEvent {
  rule: string
  tool: string
  message: string
  arguments: Record<string, unknown>
}

export interface Approval {
  id: string
  action: string
  amount: number | null
  reason: string
  payload: Record<string, unknown>
  status: string
}

export interface CallRecord {
  purpose: string
  model: string
  provider: string
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
  latency_ms: number
  from_cassette: boolean
}

export interface Span {
  name: string
  offset_ms: number
  duration_ms: number
  attributes?: Record<string, unknown>
}

export interface Trial {
  scenario_id: string
  category: string
  trial_index: number
  status: string
  error: string | null
  termination: string
  success: boolean
  turns: number
  checks: CheckResult[]
  events: TranscriptEvent[]
  rule_events: RuleEvent[]
  approvals: Approval[]
  state_diff: Record<string, unknown>
  calls: CallRecord[]
  trace_id: string | null
  trace: Span[]
  trace_url: string | null
}

export interface ScenarioDetail {
  run_id: string
  scenario_id: string
  trials: Trial[]
}

export interface Paired {
  n: number
  baseline?: number
  candidate?: number
  delta?: number
  delta_ci95?: Ci
  p_value?: number
  significant?: boolean
}

export interface Comparison {
  baseline: string
  candidate: string
  alpha: number
  metrics: Record<string, Paired>
  by_category: Record<string, Record<string, Paired>>
  newly_failing: string[]
  newly_passing: string[]
  only_in_baseline: string[]
  only_in_candidate: string[]
}

export interface CompareResponse {
  a: RunRow
  b: RunRow
  comparison: Comparison
}

export interface FailureExample {
  run_id: string
  scenario_id: string
  trial_index: number
  trace_id: string | null
  excerpt: { role: string; text: string }[]
}

export interface FailurePattern {
  reason: string
  count: number
  share: number
  scenarios: string[]
  categories: string[]
  top_details: [string, number][]
  examples: FailureExample[]
}

export interface TraceResponse {
  trace_id: string
  run_id: string
  scenario_id: string
  trial_index: number
  spans: Span[]
}

export interface Criterion {
  id: string
  question: string
  passes_when: string
  fails_when: string
  not_applicable_when?: string | null
}

export interface LabelItem {
  item_id: string
  run_id: string
  environment: string
  scenario_id: string
  trial_index: number
  category: string
  goal: string
  transcript: string
}

export interface LabelsResponse {
  rubric: { name: string; version: string; description: string; criteria: Criterion[] }
  labels: Record<string, Record<string, string>>
  items: LabelItem[]
}

export interface CalibrationMetric {
  n: number
  agreement?: number
  kappa?: number | null
  kappa_ci95?: Ci
  human_pass_rate?: number
  judge_pass_rate?: number
  confusion?: Record<string, number>
}

export interface CalibrationReport {
  rubric: string
  version: string
  judge_model: string
  n_items: number
  criteria: Record<string, CalibrationMetric>
}

export interface ApprovalRow {
  pk: number
  run_id: string | null
  scenario_id: string | null
  trial_index: number | null
  approval_id: string
  action: string
  amount: number | null
  reason: string
  payload: Record<string, unknown> | null
  status: string
  decided_by: string | null
  decided_at: string | null
  note: string | null
}
