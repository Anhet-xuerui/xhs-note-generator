import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'

import { createRun, reportUrl, subscribe } from '../api'
import type { Persona, RunEvent, RunResult } from '../types'

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

  let close: (() => void) | null = null

  const report = computed(() => (runId.value ? reportUrl(runId.value) : ''))
  const timeline = computed(() =>
    events.value.filter((event) => event.event === 'node_start' || event.event === 'node_end'),
  )
  const checks = computed(() => result.value?.meta.failed_checks ?? [])
  const usage = computed(() => result.value?.meta.usage)

  function reset() {
    close?.()
    close = null
    runId.value = ''
    events.value = []
    result.value = null
    error.value = ''
    status.value = 'idle'
  }

  async function start() {
    reset()
    status.value = 'running'
    try {
      runId.value = await createRun(persona, topic.value)
      close = subscribe(runId.value, (event: RunEvent) => {
        if (event.event === 'node_start' || event.event === 'node_end') {
          events.value.push(event)
        } else if (event.event === 'error') {
          error.value = event.message ?? '运行失败'
          status.value = 'error'
        } else if (event.event === 'result') {
          result.value = event.data ?? null
          status.value = 'done'
          close?.()
          close = null
        }
      })
    } catch (exc) {
      error.value = exc instanceof Error ? exc.message : String(exc)
      status.value = 'error'
    }
  }

  function stop() {
    close?.()
    close = null
  }

  return { persona, topic, runId, status, events, timeline, result, error, report, checks, usage, start, reset, stop }
})
