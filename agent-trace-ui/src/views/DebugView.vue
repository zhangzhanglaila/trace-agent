<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useTraceStore } from '../store/traceStore'
import NLExplanation from '../components/NLExplanation.vue'
import VerdictCard from '../components/VerdictCard.vue'
import GraphView from '../components/GraphView.vue'
import ComparisonView from '../components/ComparisonView.vue'
import DiffPanel from '../components/DiffPanel.vue'
import StepDetail from '../components/StepDetail.vue'
import FixSuggestion from '../components/FixSuggestion.vue'
import WhatIfPanel from '../components/WhatIfPanel.vue'
import BugToggle from '../components/BugToggle.vue'
import QuickRun from '../components/QuickRun.vue'
import RunTimeline from '../components/RunTimeline.vue'
import LiveAgentIndicator from '../components/LiveAgentIndicator.vue'

const store = useTraceStore()
const fileInput = ref<HTMLInputElement | null>(null)
const quickRunExpanded = ref(false)
const dragOver = ref(false)
const mainViewMode = ref<'graph' | 'compare'>('graph')
const timelineCollapsed = ref(false)

onMounted(() => {
  store.fetchDemo()
})

function onDragOver(e: DragEvent) {
  e.preventDefault()
  dragOver.value = true
}

function onDragLeave() {
  dragOver.value = false
}

function onDrop(e: DragEvent) {
  e.preventDefault()
  dragOver.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) {
    store.uploadTrace(file)
  }
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) {
    store.uploadTrace(file)
  }
}

function triggerUpload() {
  fileInput.value?.click()
}
</script>

<template>
  <div
    class="debug-view"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <!-- Drag overlay -->
    <div v-if="dragOver" class="drag-overlay">
      <div class="drag-hint">Drop trace.json here</div>
    </div>

    <!-- Loading -->
    <div v-if="store.loading" class="loading-state">
      <div class="spinner"></div>
      <p>Loading trace data...</p>
    </div>

    <!-- Error -->
    <div v-else-if="store.error && !store.traceData" class="error-state">
      <p>❌ {{ store.error }}</p>
      <button @click="store.fetchDemo()">Retry</button>
    </div>

    <!-- Main layout -->
    <template v-else-if="store.traceData">
      <!-- Top: Bug Toggle -->
      <BugToggle />

      <!-- Quick Run (collapsible) -->
      <div class="quickrun-toggle" v-if="!quickRunExpanded">
        <button @click="quickRunExpanded = true">
          ▶ Quick Run: Custom inputs
        </button>
      </div>
      <QuickRun v-if="quickRunExpanded" />
      <div class="quickrun-collapse" v-if="quickRunExpanded">
        <button @click="quickRunExpanded = false">▲ Collapse</button>
      </div>

      <!-- Live agent indicator -->
      <LiveAgentIndicator />

      <!-- Top: Natural Language Explanation -->
      <NLExplanation />

      <!-- Top: Verdict -->
      <VerdictCard />

      <!-- Middle: Mode toggle + Main view + Side panels -->
      <div class="mode-toggle-bar">
        <button :class="{ active: mainViewMode === 'graph' }" @click="mainViewMode = 'graph'">
          🌳 Graph
        </button>
        <button :class="{ active: mainViewMode === 'compare' }" @click="mainViewMode = 'compare'">
          ⬅ Compare ➡
        </button>
      </div>

      <div class="main-content">
        <RunTimeline v-model:collapsed="timelineCollapsed" />
        <div class="graph-area">
          <GraphView v-if="mainViewMode === 'graph'" />
          <ComparisonView v-if="mainViewMode === 'compare'" />
          <FixSuggestion />
          <WhatIfPanel />
        </div>
        <div class="side-panels">
          <DiffPanel />
          <StepDetail />
        </div>
      </div>

      <!-- Upload bar -->
      <div class="upload-bar">
        <input
          ref="fileInput"
          type="file"
          accept=".json"
          style="display:none"
          @change="onFileChange"
        />
        <div class="upload-left">
          <button class="upload-btn" @click="triggerUpload">
            📁 Upload trace.json
          </button>
          <span class="upload-hint">
            or <strong>drag &amp; drop</strong> any <code>trace.json</code> file onto this page
            — instant analysis
          </span>
        </div>
        <div class="upload-right">
          <a href="/demo_trace.json" download class="download-link" title="Download sample trace">
            ⬇ Sample trace
          </a>
          <span class="meta-info">
            Run A: {{ store.traceData.meta.run_a_steps }} steps ·
            Run B: {{ store.traceData.meta.run_b_steps }} steps
          </span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.debug-view {
  min-height: 100vh;
  padding: 20px 24px;
  background: #f5f7fa;
  position: relative;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

/* ── Drag overlay ── */
.drag-overlay {
  position: fixed;
  inset: 0;
  background: rgba(64, 158, 255, 0.12);
  border: 3px dashed #409EFF;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

.drag-hint {
  background: #fff;
  padding: 24px 48px;
  border-radius: 12px;
  font-size: 20px;
  font-weight: 700;
  color: #409EFF;
  box-shadow: 0 8px 32px rgba(64, 158, 255, 0.2);
}

/* ── Loading ── */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  gap: 16px;
  color: #909399;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #e4e7ed;
  border-top-color: #409EFF;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

/* ── Error ── */
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  gap: 12px;
}

.error-state button {
  padding: 8px 20px;
  background: #409EFF;
  color: #fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}

/* ── Mode toggle ── */
.mode-toggle-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.mode-toggle-bar button {
  padding: 8px 20px;
  border: 1px solid #e4e7ed;
  background: #fff;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  color: #909399;
  transition: all 0.2s;
}

.mode-toggle-bar button:hover { border-color: #409EFF; color: #409EFF; }

.mode-toggle-bar button.active {
  background: #409EFF;
  color: #fff;
  border-color: #409EFF;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.3);
}

/* ── Main layout ── */
.main-content {
  display: grid;
  grid-template-columns: auto 1fr 380px;
  gap: 16px;
  margin-bottom: 16px;
  min-height: 520px;
  align-items: start;
}

.graph-area {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.side-panels {
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
  max-height: calc(100vh - 280px);
}

/* ── Upload bar ── */
.upload-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  background: linear-gradient(135deg, #fafbff 0%, #f0f4ff 100%);
  border: 1px dashed #d9ecff;
  border-radius: 10px;
  flex-wrap: wrap;
  gap: 12px;
}

.upload-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.upload-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.upload-btn {
  padding: 8px 20px;
  background: #409EFF;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.3);
}

.upload-btn:hover {
  background: #337ecc;
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.4);
  transform: translateY(-1px);
}

.upload-hint {
  font-size: 12px;
  color: #909399;
}

.upload-hint code {
  background: #ecf5ff;
  color: #409EFF;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
}

.upload-hint strong {
  color: #606266;
}

/* ── Quick Run toggle ── */
.quickrun-toggle {
  display: flex;
  justify-content: center;
  margin-bottom: 8px;
}

.quickrun-toggle button {
  padding: 6px 16px;
  border: 1px dashed #d9ecff;
  background: #f0f7ff;
  color: #409EFF;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.quickrun-toggle button:hover {
  background: #ecf5ff;
  border-color: #409EFF;
}

.quickrun-collapse {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}

.quickrun-collapse button {
  padding: 2px 10px;
  border: none;
  background: transparent;
  color: #909399;
  font-size: 11px;
  cursor: pointer;
}

.quickrun-collapse button:hover {
  color: #409EFF;
}

.download-link {
  font-size: 12px;
  color: #409EFF;
  text-decoration: none;
  font-weight: 600;
  padding: 4px 12px;
  border: 1px solid #d9ecff;
  border-radius: 6px;
  transition: all 0.2s;
}

.download-link:hover {
  background: #ecf5ff;
}

.meta-info {
  font-size: 12px;
  color: #909399;
}

/* ── Responsive ── */
@media (max-width: 1100px) {
  .main-content {
    grid-template-columns: auto 1fr;
  }
  .side-panels {
    max-height: none;
    grid-column: 1 / -1;
  }
}

@media (max-width: 900px) {
  .main-content {
    grid-template-columns: 1fr;
  }
  .side-panels {
    max-height: none;
    grid-column: 1;
  }
}
</style>
