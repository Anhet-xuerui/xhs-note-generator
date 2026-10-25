<script setup lang="ts">
import { onUnmounted } from 'vue'

import DraftPanel from './components/DraftPanel.vue'
import PersonaForm from './components/PersonaForm.vue'
import TimelinePanel from './components/TimelinePanel.vue'
import { useRunStore } from './stores/run'

const store = useRunStore()
onUnmounted(() => store.stop())
</script>

<template>
  <header class="app-header">
    <h1>小红书多角色笔记生成</h1>
    <span>七角色讨论循环 · 读者来自另一家厂商 · 判定卡由代码算</span>
  </header>

  <main class="layout">
    <PersonaForm />
    <TimelinePanel />
    <DraftPanel />
  </main>
</template>

<style scoped>
.app-header {
  display: flex;
  gap: 16px;
  align-items: baseline;
  padding: 14px 20px;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
}
.app-header h1 {
  font-size: 16px;
  margin: 0;
}
.app-header span {
  font-size: 12px;
  color: #6b7280;
}
.layout {
  display: grid;
  grid-template-columns: 320px minmax(280px, 1fr) minmax(320px, 1.2fr);
  gap: 16px;
  padding: 16px;
  align-items: start;
}
@media (max-width: 1100px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
</style>
