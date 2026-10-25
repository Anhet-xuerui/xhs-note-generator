<script setup lang="ts">
import { computed } from 'vue'

import { useRunStore } from '../stores/run'

const store = useRunStore()

const statusText = computed(() => {
  if (store.status === 'running') return '生成中'
  if (store.status === 'done') return `完成（${store.result?.status ?? ''}）`
  if (store.status === 'error') return '失败'
  return '待开始'
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="head">
        <span class="panel-title">过程</span>
        <el-tag size="small" :type="store.status === 'error' ? 'danger' : 'info'">{{ statusText }}</el-tag>
      </div>
    </template>

    <el-alert v-if="store.error" :title="store.error" type="error" :closable="false" show-icon />

    <ul v-if="store.timeline.length" class="timeline">
      <li v-for="(event, index) in store.timeline" :key="index">
        <code class="node">{{ event.node }}</code>
        <span :class="event.event === 'node_end' ? 'ok' : 'waiting'">
          {{ event.event === 'node_end' ? '完成' : '开始' }}
        </span>
        <span class="round">第 {{ event.round }} 轮</span>
      </li>
    </ul>
    <p v-else class="empty">还没有事件。提交后这里会逐条出现。</p>
  </el-card>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.timeline {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 620px;
  overflow: auto;
}
.timeline li {
  display: flex;
  gap: 10px;
  align-items: baseline;
  padding: 6px 0;
  border-bottom: 1px dashed #e5e7eb;
  font-size: 13px;
}
.node {
  font-family: ui-monospace, Consolas, monospace;
}
.ok {
  color: #047857;
}
.waiting {
  color: #9ca3af;
}
.round {
  color: #6b7280;
  font-size: 12px;
}
.empty {
  color: #6b7280;
  font-size: 12px;
  margin: 0;
}
</style>
