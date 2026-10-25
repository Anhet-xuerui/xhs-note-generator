import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'

import {
  createRun,
  fetchPrompts,
  fetchRun,
  fetchRunPrompts,
  fetchRuns,
  reportUrl,
  resetAllPrompts,
  resetPrompt,
  savePrompt,
  subscribe,
} from '../api'
import type {
  NodeEvent,
  Persona,
  PromptItem,
  RunEvent,
  RunPromptItem,
  RunResult,
  RunSummary,
} from '../types'

function describe(exc: unknown): string {
  return exc instanceof Error ? exc.message : String(exc)
}

export const useRunStore = defineStore('run', () => {
  const persona = reactive<Persona>({
    nickname: '沪漂第三年的市场岗打工人',
    age_range: '25-30',
    city: '上海',
    occupation: '市场营销',
    goal: '涨粉',
    tone: ['自嘲', '直给'],
    real_material: [
      '被二房东坑过一个月押金，最后靠报警才要回来一半',
      '中介带我看房时说这栋楼隔音差，我当时没听懂',
    ],
    taboo: ['不提公司名'],
  })
  const topic = ref('租房第一年我终于搞清楚的事')

  const runId = ref('')
  const status = ref<'idle' | 'running' | 'done' | 'error'>('idle')
  const events = ref<RunEvent[]>([])
  const result = ref<RunResult | null>(null)
  const error = ref('')

  const runs = ref<RunSummary[]>([])
  const prompts = ref<PromptItem[]>([])
  const runPrompts = ref<RunPromptItem[]>([])
  const dirty = reactive<Record<string, boolean>>({})
  const openNode = ref<NodeEvent | null>(null)

  let close: (() => void) | null = null

  const report = computed(() => (runId.value ? reportUrl(runId.value) : ''))
  const timeline = computed(() =>
    events.value.filter((event) => event.event === 'node_start' || event.event === 'node_end'),
  )
  const nodes = computed<NodeEvent[]>(() =>
    events.value
      .filter((event): event is NodeEvent => event.event === 'node_end')
      .sort((left, right) => (left.seq ?? 0) - (right.seq ?? 0)),
  )
  const rounds = computed(() => {
    const grouped = new Map<number, NodeEvent[]>()
    for (const node of nodes.value) {
      const round = node.round ?? 1
      const bucket = grouped.get(round) ?? []
      bucket.push(node)
      grouped.set(round, bucket)
    }
    return [...grouped.entries()].map(([round, items]) => ({ round, nodes: items }))
  })
  const checks = computed(() => result.value?.meta.failed_checks ?? [])
  const usage = computed(() => result.value?.meta.usage)
  const editedRoles = computed(() =>
    prompts.value.filter((item) => item.source === 'edited').map((item) => item.role),
  )
  const promptByRole = computed<Record<string, PromptItem>>(() =>
    Object.fromEntries(prompts.value.map((item) => [item.role, item])),
  )
  const runPromptByRole = computed<Record<string, RunPromptItem>>(() =>
    Object.fromEntries(runPrompts.value.map((item) => [item.role, item])),
  )

  function isDirty(role: string): boolean {
    return Boolean(dirty[role])
  }

  function reset() {
    close?.()
    close = null
    runId.value = ''
    events.value = []
    result.value = null
    error.value = ''
    status.value = 'idle'
    runPrompts.value = []
  }

  function attach(id: string) {
    close?.()
    close = null
    runId.value = id
    events.value = []
    result.value = null
    error.value = ''
    close = subscribe(id, onEvent)
  }

  function onEvent(event: RunEvent) {
    if (event.event === 'node_start' || event.event === 'node_end') {
      events.value.push(event)
      return
    }
    if (event.event === 'error') {
      error.value = event.message ?? '运行失败'
      status.value = 'error'
      return
    }
    if (event.event === 'result') {
      result.value = event.data ?? null
      status.value = 'done'
      close?.()
      close = null
      void loadRuns()
    }
  }

  async function loadPrompts() {
    prompts.value = (await fetchPrompts()).items
  }

  async function loadRuns() {
    runs.value = (await fetchRuns()).items
  }

  async function loadRunPrompts(id: string) {
    runPrompts.value = (await fetchRunPrompts(id)).items
  }

  async function start() {
    reset()
    status.value = 'running'
    try {
      const { run_id } = await createRun(persona, topic.value)
      attach(run_id)
      await loadRunPrompts(run_id)
      void loadRuns()
    } catch (exc) {
      error.value = describe(exc)
      status.value = 'error'
    }
  }

  async function viewRun(id: string) {
    if (id === runId.value && status.value === 'running') return
    attach(id)
    status.value = 'running'
    try {
      const snapshot = await fetchRun(id)
      result.value = snapshot
      status.value = snapshot.status === 'running' ? 'running' : 'done'
      await loadRunPrompts(id)
    } catch (exc) {
      error.value = describe(exc)
      status.value = 'error'
    }
  }

  async function save(role: string, text: string) {
    await savePrompt(role, text)
    dirty[role] = false
    await loadPrompts()
  }

  async function resetOne(role: string) {
    await resetPrompt(role)
    dirty[role] = false
    await loadPrompts()
  }

  async function resetEvery() {
    prompts.value = (await resetAllPrompts()).items
    for (const role of Object.keys(dirty)) dirty[role] = false
  }

  function markDirty(role: string) {
    dirty[role] = true
  }

  function stop() {
    close?.()
    close = null
  }

  return {
    persona,
    topic,
    runId,
    status,
    events,
    nodes,
    rounds,
    timeline,
    result,
    error,
    runs,
    prompts,
    runPrompts,
    promptByRole,
    runPromptByRole,
    editedRoles,
    openNode,
    report,
    checks,
    usage,
    isDirty,
    markDirty,
    loadPrompts,
    loadRuns,
    loadRunPrompts,
    start,
    viewRun,
    save,
    resetOne,
    resetEvery,
    reset,
    stop,
  }
})
