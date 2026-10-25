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
  }
}

export interface RunEvent {
  event: string
  node?: string
  round?: number
  message?: string
  data?: RunResult
}
