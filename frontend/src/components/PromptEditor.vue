<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { contractWarnings } from '../promptGuard'
import { useRunStore } from '../stores/run'
import { ROLE_LABELS } from '../types'

const store = useRunStore()
const props = defineProps<{ role: string }>()

const emit = defineEmits<{ saved: [] }>()

const item = computed(() => store.promptByRole[props.role])

const draft = ref('')
const saving = ref(false)
const message = ref('')

watch(
  () => [props.role, item.value?.text] as const,
  () => {
    draft.value = item.value?.text ?? ''
    message.value = ''
  },
  { immediate: true },
)

const dirty = computed(() => draft.value !== (item.value?.text ?? ''))
const warnings = computed(() => contractWarnings(props.role, draft.value))

async function save() {
  saving.value = true
  message.value = ''
  try {
    await store.save(props.role, draft.value)
    message.value = '已保存，下一次生成生效'
    emit('saved')
  } catch (exc) {
    message.value = exc instanceof Error ? exc.message : String(exc)
  } finally {
    saving.value = false
  }
}

async function resetToDefault() {
  saving.value = true
  message.value = ''
  try {
    await store.resetOne(props.role)
    message.value = '已恢复默认'
  } catch (exc) {
    message.value = exc instanceof Error ? exc.message : String(exc)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="editor">
    <div class="bar">
      <span class="meta">
        {{ ROLE_LABELS[role] ?? role }} · 当前生效版
        <code class="mono">{{ item?.sha8 }}</code>
      </span>
      <el-tag v-if="item?.source === 'edited'" type="warning" size="small" effect="plain">已改动</el-tag>
      <el-tag v-else size="small" type="info" effect="plain">默认</el-tag>
    </div>

    <el-alert
      v-for="warning in warnings"
      :key="warning"
      :title="warning"
      type="warning"
      :closable="false"
      show-icon
      class="warn"
    />

    <el-input
      v-model="draft"
      type="textarea"
      :rows="18"
      resize="vertical"
      class="textarea"
      placeholder="改这一版，保存后在下一次生成时生效"
    />

    <div class="actions">
      <el-button type="primary" :loading="saving" :disabled="!dirty" @click="save">保存这一版</el-button>
      <el-button :loading="saving" @click="resetToDefault">恢复默认</el-button>
      <span class="meta">{{ draft.length }} 字符</span>
    </div>
    <p v-if="message" class="meta">{{ message }}</p>
  </div>
</template>

<style scoped>
.editor {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.bar {
  display: flex;
  align-items: center;
  gap: 8px;
}
.warn {
  margin: 0;
}
.textarea :deep(textarea) {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
}
.actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
