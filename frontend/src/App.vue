<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

import AppHeader from './components/AppHeader.vue'
import DraftPanel from './components/DraftPanel.vue'
import NodeDrawer from './components/NodeDrawer.vue'
import NodeTimeline from './components/NodeTimeline.vue'
import PersonaForm from './components/PersonaForm.vue'
import { useRunStore } from './stores/run'
import type { NodeEvent } from './types'

const store = useRunStore()

onMounted(() => {
  void store.loadPrompts()
  void store.loadRuns()
})
onUnmounted(() => store.stop())

function openDrawer(node: NodeEvent) {
  store.openNode = node
}
</script>

<template>
  <AppHeader />
  <main class="layout">
    <PersonaForm />
    <NodeTimeline @open="openDrawer" />
    <DraftPanel />
  </main>
  <NodeDrawer :node="store.openNode" @close="store.openNode = null" />
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr) 380px;
  gap: 16px;
  padding: 16px 20px 40px;
  align-items: start;
}
@media (max-width: 1100px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
</style>
