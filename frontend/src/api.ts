import type {
  Persona,
  PromptsResponse,
  RunEvent,
  RunPromptItem,
  RunResult,
  RunSummary,
} from './types'

/** 与后端同一 origin（构建产物由 FastAPI 托管）；开发时走 vite 代理。 */
const BASE = ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init)
  if (!response.ok) {
    let detail = `请求失败：${response.status}`
    try {
      const body = (await response.json()) as { detail?: string }
      if (body?.detail) detail = body.detail
    } catch {
      /* 非 JSON 错误体：保留状态码 */
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

export function createRun(persona: Persona, topic: string): Promise<{ run_id: string }> {
  return request<{ run_id: string }>('/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ persona, topic }),
  })
}

export function fetchRun(runId: string): Promise<RunResult> {
  return request<RunResult>(`/runs/${runId}`)
}

export function fetchRuns(): Promise<{ items: RunSummary[] }> {
  return request<{ items: RunSummary[] }>('/runs')
}

export function fetchPrompts(): Promise<PromptsResponse> {
  return request<PromptsResponse>('/prompts')
}

export function fetchRunPrompts(runId: string): Promise<{ items: RunPromptItem[] }> {
  return request<{ items: RunPromptItem[] }>(`/runs/${runId}/prompts`)
}

export function savePrompt(role: string, text: string): Promise<{ sha8: string; source: string }> {
  return request<{ sha8: string; source: string }>(`/prompts/${role}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
}

export function resetPrompt(role: string): Promise<{ sha8: string; source: string }> {
  return request<{ sha8: string; source: string }>(`/prompts/${role}`, { method: 'DELETE' })
}

export function resetAllPrompts(): Promise<PromptsResponse> {
  return request<PromptsResponse>('/prompts', { method: 'DELETE' })
}

/**
 * EventSource 只支持 GET，所以生成必须拆两步：先 POST 拿 id，再订阅（§10 的实现坑）。
 * 返回 close 函数，供组件卸载或切换 run 时断开。
 */
export function subscribe(runId: string, onEvent: (event: RunEvent) => void): () => void {
  const source = new EventSource(`${BASE}/runs/${runId}/events`)
  const handle = (raw: MessageEvent) => {
    try {
      onEvent(JSON.parse(raw.data) as RunEvent)
    } catch {
      /* 坏行忽略，不打断时间线 */
    }
  }
  source.onmessage = handle
  for (const name of ['node_start', 'node_end', 'result', 'error', 'run_started', 'done']) {
    source.addEventListener(name, handle as EventListener)
  }
  return () => source.close()
}

export function reportUrl(runId: string): string {
  return `${BASE}/runs/${runId}/report`
}
