export interface Persona {
  nickname: string
  age_range: string
  city: string
  occupation: string
  goal: string
  tone: string[]
  real_material: string[]
  taboo: string[]
}

export interface FailedCheck {
  code: string
  label: string
  detail: string
}

export interface GateFinding {
  rule_id: string
  severity: string
  matched: string
  false_positive: boolean
  hint: string
}

export interface NodeUsage {
  input_tokens: number
  output_tokens: number
  cost_cny: number
  calls: number
}

export interface RunResult {
  title: string | null
  cover_text: string | null
  body: string | null
  tags: string[]
  status: string
  meta: {
    rounds_used: number
    best_round: number | null
    failed_checks: FailedCheck[]
    usage: { cost_cny: number; calls: number; elapsed_s: number }
    smell?: { before: number; after: number; fidelity: string } | null
    gate_findings?: GateFinding[]
    prompts_edited?: string[]
    prompts_sha8?: Record<string, string>
  }
}

export interface RunEvent {
  event: string
  node?: string
  round?: number
  message?: string
  data?: RunResult
}

/** node_end 比 node_start 多带产物、耗时、花费、降级标记（D10-5）。 */
export interface NodeEvent extends RunEvent {
  attempt?: number
  seq?: number
  ok?: boolean
  degraded?: boolean
  degraded_reason?: string
  error?: string
  elapsed_ms?: number
  usage?: NodeUsage
  prompt_sha8?: string
  product?: unknown
}

/** 时间线上的一行：`node_start` 先占位（pending），`node_end` 再补齐结果。 */
export interface NodeRow extends NodeEvent {
  pending?: boolean
}

export interface PromptItem {
  role: string
  text: string
  default_text: string
  source: 'default' | 'edited'
  sha8: string
  updated_at: string | null
}

export interface PromptsResponse {
  roles: string[]
  items: PromptItem[]
}

export interface RunPromptItem {
  role: string
  text: string
  sha8: string
  source: string
}

export interface RunSummary {
  run_id: string
  topic: string
  status: string | null
  created_at: string | null
  prompts_edited: string[]
}

export const ROLE_LABELS: Record<string, string> = {
  profile: '画像官',
  planner: '策划',
  writer: '主笔',
  reader: '读者',
  cover: '封面',
  humanizer: '人味校订',
  gatekeeper: '守门人',
}
