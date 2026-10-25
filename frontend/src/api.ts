import type { Persona, RunEvent } from './types'

/** 与后端同一 origin（构建产物由 FastAPI 托管）；开发时走 vite 代理。 */
const BASE = ''

export async function createRun(persona: Persona, topic: string): Promise<string> {
  const response = await fetch(`${BASE}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ persona, topic }),
  })
  if (!response.ok) {
    throw new Error(`提交失败：${response.status}`)
  }
  const payload = (await response.json()) as { run_id: string }
  return payload.run_id
}

/**
 * EventSource 只支持 GET，所以生成必须拆两步：先 POST 拿 id，再订阅（§10 的实现坑）。
 * 返回 close 函数，供组件卸载时断开。
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
  for (const name of ['node_start', 'node_end', 'result', 'error', 'run_started']) {
    source.addEventListener(name, handle as EventListener)
  }
  return () => source.close()
}

export function reportUrl(runId: string): string {
  return `${BASE}/runs/${runId}/report`
}
