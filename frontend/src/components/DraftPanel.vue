<script setup lang="ts">
import { computed } from 'vue'

import { useRunStore } from '../stores/run'

const store = useRunStore()

const paragraphs = computed(() => (store.result?.body ?? '').split(/\n{2,}/).filter(Boolean))
const cover = computed(() => store.result?.cover_text ?? '')
const passedCount = computed(
  () => (store.result?.meta.gate_findings ?? []).filter((item) => item.false_positive).length,
)
const gateHits = computed(() =>
  (store.result?.meta.gate_findings ?? []).filter((item) => !item.false_positive),
)
</script>

<template>
  <el-card shadow="never">
    <template #header><span class="panel-title">结果</span></template>

    <template v-if="store.result">
      <div class="cover">{{ cover || '（无封面文案）' }}</div>
      <h3 class="title">{{ store.result.title }}</h3>
      <p v-for="(text, index) in paragraphs" :key="index" class="body">{{ text }}</p>
      <div class="tags">
        <el-tag v-for="tag in store.result.tags" :key="tag" size="small" type="info" class="tag">{{ tag }}</el-tag>
      </div>

      <el-divider />
      <p class="kv">
        状态 <b>{{ store.result.status }}</b>｜{{ store.result.meta.rounds_used }} 轮｜
        交付第 {{ store.result.meta.best_round ?? '—' }} 轮
        <template v-if="store.usage">
          ｜{{ store.usage.calls }} 次调用｜{{ store.usage.cost_cny }} 元｜{{ store.usage.elapsed_s }} 秒
        </template>
      </p>
      <p v-if="store.result.meta.smell" class="kv">
        AI 味 {{ store.result.meta.smell.before }} → {{ store.result.meta.smell.after }}
        （保真：{{ store.result.meta.smell.fidelity }}）
      </p>
      <p v-if="passedCount" class="kv">守门人：{{ passedCount }} 条命中被判误报放行</p>
      <p v-if="gateHits.length" class="kv danger">
        守门人命中：{{ gateHits.map((hit) => hit.matched).join('、') }}
      </p>

      <ul v-if="store.checks.length" class="checks">
        <li v-for="check in store.checks" :key="check.code">
          <b>{{ check.label }}</b>：{{ check.detail }}
        </li>
      </ul>

      <p>
        <el-link :href="store.report" target="_blank" type="primary">打开完整过程报告 →</el-link>
      </p>
    </template>
    <p v-else class="empty">提交一次生成，这里会显示标题、封面、正文与判定卡。</p>
  </el-card>
</template>

<style scoped>
.cover {
  display: inline-block;
  background: #fff1f2;
  color: #be123c;
  padding: 4px 10px;
  border-radius: 6px;
  font-weight: 600;
  font-size: 13px;
}
.title {
  font-size: 16px;
  margin: 12px 0 8px;
}
.body {
  font-size: 14px;
  line-height: 1.8;
  margin: 0 0 10px;
}
.tags {
  margin-top: 6px;
}
.tag {
  margin: 0 6px 6px 0;
}
.kv {
  font-size: 12px;
  color: #6b7280;
  margin: 4px 0;
}
.danger {
  color: #b91c1c;
}
.checks {
  font-size: 12px;
  color: #b91c1c;
  padding-left: 18px;
}
.empty {
  color: #6b7280;
  font-size: 12px;
  margin: 0;
}
</style>
