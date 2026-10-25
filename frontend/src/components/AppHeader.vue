<script setup lang="ts">
import { computed } from 'vue'

import { useRunStore } from '../stores/run'

const store = useRunStore()

const statusText = computed(() => {
  if (store.status === 'running') return '生成中'
  if (store.status === 'done') return `完成（${store.result?.status ?? '—'}）`
  if (store.status === 'error') return '失败'
  return '待开始'
})

const statusType = computed(() => {
  if (store.status === 'error') return 'danger'
  if (store.status === 'running') return 'warning'
  if (store.status === 'done') return 'success'
  return 'info'
})

function switchRun(id: string) {
  if (id && id !== store.runId) void store.viewRun(id)
}

function label(runId: string): string {
  const found = store.runs.find((item) => item.run_id === runId)
  if (!found) return runId
  const mark = found.prompts_edited.length ? ' · 改过 prompt' : ''
  return `${found.topic} · ${found.status ?? '…'}${mark}`
}
</script>

<template>
  <header class="app-header">
    <div class="brand">
      <h1>小红书多角色笔记生成</h1>
      <span class="meta">七角色讨论循环 · 读者来自另一家厂商 · 判定卡由代码算</span>
    </div>

    <div class="controls">
      <el-select
        v-if="store.runs.length"
        :model-value="store.runId"
        size="small"
        class="picker"
        placeholder="切回历史 run"
        @change="switchRun"
      >
        <el-option
          v-for="run in store.runs"
          :key="run.run_id"
          :value="run.run_id"
          :label="label(run.run_id)"
        />
      </el-select>

      <el-tag :type="statusType" size="small" effect="plain">{{ statusText }}</el-tag>

      <el-tag v-if="store.editedRoles.length" type="warning" size="small" effect="plain">
        已修改 {{ store.editedRoles.length }} 个 prompt
      </el-tag>

      <span v-if="store.usage" class="meta">
        {{ store.usage.calls }} 次调用 · {{ store.usage.cost_cny }} 元 ·
        {{ store.usage.elapsed_s }} 秒
      </span>

      <el-link v-if="store.runId" :href="store.report" target="_blank" type="primary" :underline="false">
        报告 →
      </el-link>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  display: flex;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  padding: 12px 20px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
  position: sticky;
  top: 0;
  z-index: 10;
}
.brand {
  display: flex;
  align-items: baseline;
  gap: 12px;
  min-width: 0;
}
.brand h1 {
  font-size: 15px;
  font-weight: 600;
  margin: 0;
  white-space: nowrap;
}
.controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.picker {
  width: 240px;
}
</style>
