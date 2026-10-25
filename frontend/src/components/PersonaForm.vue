<script setup lang="ts">
import { computed } from 'vue'

import { useRunStore } from '../stores/run'

const store = useRunStore()

// textarea ↔ string[]：一行一条，逗号分隔的用 split
const materials = computed({
  get: () => store.persona.real_material.join('\n'),
  set: (value: string) =>
    (store.persona.real_material = value
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)),
})

function csv(value: string): string[] {
  return value
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

const tone = computed({
  get: () => store.persona.tone.join('、'),
  set: (value: string) => (store.persona.tone = csv(value)),
})

const taboo = computed({
  get: () => store.persona.taboo.join('、'),
  set: (value: string) => (store.persona.taboo = csv(value)),
})
</script>

<template>
  <el-card shadow="never">
    <template #header><span class="panel-title">输入</span></template>

    <el-form label-position="top" size="small">
      <el-form-item label="身份">
        <el-input v-model="store.persona.nickname" />
      </el-form-item>
      <el-form-item label="年龄 / 城市 / 职业">
        <div class="row">
          <el-input v-model="store.persona.age_range" />
          <el-input v-model="store.persona.city" />
          <el-input v-model="store.persona.occupation" />
        </div>
      </el-form-item>
      <el-form-item label="目标">
        <el-input v-model="store.persona.goal" />
      </el-form-item>
      <el-form-item label="语气（顿号或逗号分隔）">
        <el-input v-model="tone" />
      </el-form-item>
      <el-form-item label="真实经历（一行一条，这是反 AI 味的原料）">
        <el-input v-model="materials" type="textarea" :rows="4" />
      </el-form-item>
      <el-form-item label="禁区">
        <el-input v-model="taboo" />
      </el-form-item>
      <el-form-item label="主题">
        <el-input v-model="store.topic" />
      </el-form-item>

      <el-button
        type="primary"
        class="submit"
        :loading="store.status === 'running'"
        :disabled="store.status === 'running'"
        @click="store.start()"
      >
        {{ store.status === 'running' ? '生成中…' : '开始生成' }}
      </el-button>
    </el-form>

    <p class="hint">
      {{ store.runId ? `run_id：${store.runId}` : '提交后中间栏会实时滚动七个节点的起止。' }}
    </p>
  </el-card>
</template>

<style scoped>
.row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
  width: 100%;
}
.submit {
  width: 100%;
}
.hint {
  margin: 10px 0 0;
  font-size: 12px;
  color: #6b7280;
  word-break: break-all;
}
</style>
