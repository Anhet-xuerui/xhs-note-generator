<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { useRunStore } from '../stores/run'
import { ROLE_LABELS, type NodeEvent } from '../types'
import PromptEditor from './PromptEditor.vue'

const store = useRunStore()
const props = defineProps<{ node: NodeEvent | null }>()
const emit = defineEmits<{ close: [] }>()

const tab = ref<'product' | 'prompt' | 'edit'>('product')

watch(
  () => props.node?.seq,
  () => {
    tab.value = 'product'
  },
)

const role = computed(() => props.node?.node ?? '')
const label = computed(() => ROLE_LABELS[role.value] ?? role.value)
const runPrompt = computed(() => store.runPromptByRole[role.value])
const product = computed(() => JSON.stringify(props.node?.product ?? {}, null, 2))
const upstream = computed(() =>
  store.nodes.filter(
    (item) => (item.round ?? 1) === (props.node?.round ?? 1) && (item.seq ?? 0) < (props.node?.seq ?? 0),
  ),
)

function duration(ms: number | undefined): string {
  if (!ms) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}
</script>

<template>
  <el-drawer
    :model-value="node !== null"
    :size="560"
    direction="rtl"
    :with-header="true"
    @close="emit('close')"
  >
    <template #header>
      <div class="head">
        <strong>{{ label }}</strong>
        <span class="meta mono">{{ role }}</span>
        <el-tag size="small" type="info">第 {{ node?.round ?? '—' }} 轮</el-tag>
        <el-tag v-if="(node?.attempt ?? 1) > 1" size="small" type="info" effect="plain">第 {{ node?.attempt }} 次</el-tag>
      </div>
    </template>

    <div v-if="node" class="body">
      <el-alert
        v-if="node.degraded"
        type="warning"
        :closable="false"
        show-icon
        :title="`这一步走了兜底：${node.degraded_reason ?? '原因未记录'}`"
      />
      <el-alert
        v-if="node.ok === false"
        type="error"
        :closable="false"
        show-icon
        :title="`调用失败：${node.error ?? '未知错误'}`"
      />

      <div class="stats">
        <span>耗时 {{ duration(node.elapsed_ms) }}</span>
        <span>花费 {{ (node.usage?.cost_cny ?? 0).toFixed(4) }} 元</span>
        <span>{{ node.usage?.calls ?? 0 }} 次调用</span>
        <span class="mono">prompt {{ node.prompt_sha8 }}</span>
      </div>

      <div v-if="upstream.length" class="upstream">
        <span class="meta">上游：</span>
        <el-link
          v-for="item in upstream"
          :key="item.seq"
          type="primary"
          :underline="false"
          @click="store.openNode = item"
        >
          {{ ROLE_LABELS[item.node ?? ''] ?? item.node }}
        </el-link>
      </div>

      <el-tabs v-model="tab">
        <el-tab-pane label="产物" name="product">
          <pre class="mono box">{{ product }}</pre>
        </el-tab-pane>
        <el-tab-pane label="本轮 prompt（只读）" name="prompt">
          <p class="meta">
            这个 run 当时用的文本，只读。改它不会影响这次运行——要改的是「编辑下一版」。
          </p>
          <pre class="mono box">{{ runPrompt?.text ?? '这次 run 没有 prompt 快照' }}</pre>
        </el-tab-pane>
        <el-tab-pane label="编辑下一版" name="edit">
          <PromptEditor :role="role" />
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-drawer>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.stats {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 12px;
  color: var(--muted);
}
.upstream {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
.box {
  white-space: pre-wrap;
  word-break: break-word;
  background: #f9fafb;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  font-size: 12px;
  line-height: 1.6;
  max-height: 52vh;
  overflow: auto;
  margin: 0;
}
</style>
