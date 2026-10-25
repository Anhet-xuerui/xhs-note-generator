<script setup lang="ts">
import { computed } from 'vue'

import { useRunStore } from '../stores/run'
import { ROLE_LABELS, type NodeEvent, type NodeRow } from '../types'

const store = useRunStore()
const emit = defineEmits<{ open: [node: NodeEvent] }>()

const statusText = computed(() => {
  if (store.status === 'running') return '生成中'
  if (store.status === 'done') return `完成（${store.result?.status ?? '—'}）`
  if (store.status === 'error') return '失败'
  return '待开始'
})

function rowState(node: NodeRow): { text: string; kind: string } {
  if (node.pending) return { text: '运行中', kind: 'waiting' }
  if (node.ok === false) return { text: '失败', kind: 'bad' }
  if (node.degraded) return { text: '降级', kind: 'warn' }
  return { text: '完成', kind: 'ok' }
}

function duration(node: NodeRow): string {
  if (node.pending) return '…'
  const ms = node.elapsed_ms ?? 0
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

function cost(node: NodeRow): string {
  if (node.pending) return '…'
  const value = node.usage?.cost_cny ?? 0
  return value ? `${value.toFixed(4)} 元` : '—'
}
</script>

<template>
  <el-card shadow="never" class="panel">
    <template #header>
      <div class="head">
        <span class="panel-title">过程</span>
        <el-tag size="small" :type="store.status === 'error' ? 'danger' : 'info'">
          {{ statusText }}
        </el-tag>
      </div>
    </template>

    <el-alert v-if="store.error" :title="store.error" type="error" :closable="false" show-icon />

    <template v-if="store.rounds.length">
      <section v-for="group in store.rounds" :key="group.round" class="round">
        <div class="round-head">
          <span>第 {{ group.round }} 轮</span>
          <span class="meta">{{ group.nodes.length }} 个节点</span>
        </div>
        <button
          v-for="node in group.nodes"
          :key="node.seq"
          type="button"
          class="node"
          @click="emit('open', node)"
        >
          <span class="dot" :class="rowState(node).kind" />
          <span class="name">{{ ROLE_LABELS[node.node ?? ''] ?? node.node }}</span>
          <span class="code mono">{{ node.node }}</span>
          <span class="tags">
            <el-tag v-if="(node.attempt ?? 1) > 1" size="small" type="info" effect="plain">复核</el-tag>
            <el-tag v-if="node.degraded" size="small" type="warning" effect="plain">降级</el-tag>
            <el-tag v-if="node.ok === false" size="small" type="danger" effect="plain">失败</el-tag>
          </span>
          <span class="meta time">{{ duration(node) }}</span>
          <span class="meta cost">{{ cost(node) }}</span>
        </button>
      </section>
    </template>
    <p v-else class="empty">
      点「开始生成」后，这里会逐个出现七个角色；正在跑的那个显示「运行中」。
    </p>
  </el-card>
</template>

<style scoped>
.panel {
  min-height: 320px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.round {
  margin-bottom: 16px;
}
.round-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 4px 0 6px;
  font-size: 12px;
  color: var(--muted);
  border-bottom: 1px dashed var(--line);
  margin-bottom: 4px;
}
.node {
  display: grid;
  grid-template-columns: 10px 88px minmax(0, 1fr) auto 56px 76px;
  gap: 10px;
  align-items: center;
  width: 100%;
  padding: 8px 6px;
  background: transparent;
  border: 0;
  border-radius: 6px;
  text-align: left;
  font: inherit;
  color: inherit;
  cursor: pointer;
}
.node:hover {
  background: #f9fafb;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #d1d5db;
}
.dot.ok {
  background: #059669;
}
.dot.waiting {
  background: #9ca3af;
}
.dot.warn {
  background: #d97706;
}
.dot.bad {
  background: #dc2626;
}
.name {
  font-size: 13px;
}
.code {
  font-size: 12px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tags {
  display: flex;
  gap: 4px;
}
.time,
.cost {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.empty {
  color: var(--muted);
  font-size: 12px;
  margin: 8px 0 0;
}
</style>
