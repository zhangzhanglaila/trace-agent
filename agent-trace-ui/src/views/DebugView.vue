<script setup lang="ts">
import { ref } from 'vue'
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
import DemoConclusion from '../components/DemoConclusion.vue'

const store = useTraceStore()
const fileInput = ref<HTMLInputElement | null>(null)
const quickRunExpanded = ref(false)
const dragOver = ref(false)
const mainViewMode = ref<'graph' | 'compare'>('graph')
const timelineCollapsed = ref(false)
const demoRunning = ref(false)

async function runDemoAgent() {
  demoRunning.value = true
  quickRunExpanded.value = true
  timelineCollapsed.value = false
  await store.runDemo()
  demoRunning.value = false
}

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

    <!-- Welcome / empty state -->
    <div v-if="!store.traceData && !store.loading && !store.error" class="welcome-state">
      <div class="welcome-card">
        <div class="welcome-icon">◉</div>
        <h1 class="welcome-title">AgentTrace</h1>
        <p class="welcome-subtitle">
          AI Agent Debugger — compare two runs and understand<br />
          <strong>WHY</strong> your agent behaved differently.
        </p>

        <button
          class="welcome-demo-btn"
          @click="runDemoAgent"
          :disabled="demoRunning"
        >
          <span v-if="demoRunning" class="spinner-inline"></span>
          <span v-else class="welcome-btn-icon">▶</span>
          {{ demoRunning ? 'Running demo agent...' : 'Run Demo Agent' }}
        </button>

        <p class="welcome-hint">
          Runs a pre-built Travel Planner agent with a known bug.<br />
          No setup required — see the full debug experience in one click.
        </p>

        <div class="welcome-divider">
          <span>or</span>
        </div>

        <div class="welcome-upload">
          <button class="welcome-upload-btn" @click="triggerUpload">
            Upload a trace.json file
          </button>
          <p class="welcome-upload-hint">
            Drag &amp; drop any <code>trace.json</code> onto this page
          </p>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="store.loading" class="loading-state">
      <div class="spinner"></div>
      <p v-if="demoRunning">Running Travel Planner agent with bug enabled...</p>
      <p v-else>Loading trace data...</p>
    </div>

    <!-- Error -->
    <div v-if="store.error && !store.traceData && !store.loading" class="error-state">
      <p>Failed to load</p>
      <p class="error-detail">{{ store.error }}</p>
      <button @click="runDemoAgent">Retry</button>
    </div>

    <!-- Main layout -->
    <template v-if="store.traceData">
      <!-- Demo conclusion (first-screen verdict) -->
      <DemoConclusion />

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

      <div id="main-content" class="main-content">
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

      <!-- Fix prompt (after demo with bug) -->
      <div v-if="store.demoRunComplete && !store.whatIfData && !store.whatIfLoading" class="fix-prompt">
        <div class="fix-prompt-text">
          <strong>Bug case loaded.</strong> See what the fix looks like?
        </div>
        <button class="fix-prompt-btn" @click="store.fetchWhatIf()">
          Show Fix
        </button>
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

/* ── Welcome / empty state ── */
.welcome-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 80vh;
  padding: 40px 20px;
}

.welcome-card {
  text-align: center;
  max-width: 480px;
}

.welcome-icon {
  font-size: 48px;
  color: #409EFF;
  margin-bottom: 16px;
  opacity: 0.8;
}

.welcome-title {
  font-size: 32px;
  font-weight: 800;
  color: #303133;
  margin: 0 0 8px;
  letter-spacing: -0.5px;
}

.welcome-subtitle {
  font-size: 15px;
  color: #606266;
  line-height: 1.7;
  margin: 0 0 28px;
}

.welcome-subtitle strong {
  color: #409EFF;
}

.welcome-demo-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 14px 40px;
  background: linear-gradient(135deg, #409EFF, #337ecc);
  color: #fff;
  border: none;
  border-radius: 10px;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 4px 20px rgba(64, 158, 255, 0.35);
}

.welcome-demo-btn:hover:not(:disabled) {
  box-shadow: 0 6px 28px rgba(64, 158, 255, 0.5);
  transform: translateY(-2px);
}

.welcome-demo-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
  transform: none;
}

.welcome-btn-icon {
  font-size: 18px;
}

.spinner-inline {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

.welcome-hint {
  font-size: 12px;
  color: #909399;
  margin: 16px 0 0;
  line-height: 1.6;
}

.welcome-divider {
  display: flex;
  align-items: center;
  gap: 16px;
  margin: 32px 0;
  color: #C0C4CC;
  font-size: 12px;
}

.welcome-divider::before,
.welcome-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: #e4e7ed;
}

.welcome-upload-btn {
  padding: 10px 24px;
  background: #fff;
  border: 1px solid #d9ecff;
  color: #409EFF;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.welcome-upload-btn:hover {
  background: #ecf5ff;
  border-color: #409EFF;
}

.welcome-upload-hint {
  font-size: 12px;
  color: #C0C4CC;
  margin-top: 8px;
}

.welcome-upload-hint code {
  background: #f5f7fa;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 11px;
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
/* ── Fix prompt ── */
.fix-prompt {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 12px 20px;
  background: linear-gradient(135deg, #fdf6ec, #fef0e6);
  border: 1px solid #faecd8;
  border-radius: 8px;
  margin-bottom: 12px;
}

.fix-prompt-text {
  font-size: 13px;
  color: #E6A23C;
}

.fix-prompt-text strong {
  color: #cf7b1d;
}

.fix-prompt-btn {
  padding: 6px 18px;
  background: #E6A23C;
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.fix-prompt-btn:hover {
  background: #cf7b1d;
}

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
