<script setup lang="ts">
import { computed } from 'vue'
import { useTraceStore } from '../store/traceStore'

const store = useTraceStore()
const collapsed = defineModel<boolean>('collapsed', { default: false })

const visibleRuns = computed(() => store.runs.slice(0, 50))

function handleRunClick(runId: string) {
  if (store.compareMode) {
    store.setCompareBase(runId)
  } else {
    store.loadRun(runId)
  }
}

function statusIcon(run: typeof store.runs[0]) {
  const td = run.traceData
  if (!td) return '?'
  const b = td.output?.run_b || ''
  if (b.includes('[FAIL]')) return '!'
  if (b.includes('[PARTIAL]')) return '~'
  return ''
}

function statusClass(run: typeof store.runs[0]) {
  const td = run.traceData
  if (!td) return ''
  const b = td.output?.run_b || ''
  if (b.includes('[FAIL]')) return 'err'
  if (b.includes('[PARTIAL]')) return 'warn'
  return 'ok'
}

function timeAgo(ts: number) {
  const sec = Math.floor((Date.now() - ts) / 1000)
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m`
  return `${Math.floor(sec / 3600)}h`
}

function diffSign(n: number) {
  if (n > 0) return `+${n}`
  return `${n}`
}

function diffClass(n: number) {
  if (n > 0) return 'diff-pos'
  if (n < 0) return 'diff-neg'
  return ''
}
</script>

<template>
  <div class="run-timeline" :class="{ collapsed }">
    <div class="rt-header">
      <span class="rt-title" v-if="!collapsed">Runs</span>
      <div class="rt-header-actions" v-if="!collapsed">
        <button
          v-if="!store.compareMode"
          class="rt-compare-btn"
          @click="store.startCompare()"
          :disabled="store.runs.length < 2"
          title="Compare two runs"
        >
          Compare
        </button>
        <button
          v-else
          class="rt-compare-btn active"
          @click="store.cancelCompare()"
        >
          Cancel
        </button>
        <button class="rt-toggle" @click="collapsed = !collapsed">
          ◀
        </button>
      </div>
      <button v-else class="rt-toggle" @click="collapsed = !collapsed">
        ▶
      </button>
    </div>

    <template v-if="!collapsed">
      <div v-if="store.compareMode" class="rt-compare-hint">
        Select a baseline run to compare against current
      </div>

      <div class="rt-list">
        <button
          v-for="run in visibleRuns"
          :key="run.id"
          class="rt-item"
          :class="{
            active: run.id === store.activeRunId && !store.compareMode,
            target: run.id === store.activeRunId && store.compareMode,
            baseline: run.id === store.compareBaseRunId,
          }"
          @click="handleRunClick(run.id)"
        >
          <span class="rt-run-num">#{{ run.runNumber }}</span>
          <span class="rt-run-label">{{ run.label }}</span>
          <span class="rt-run-status" :class="statusClass(run)">
            {{ statusIcon(run) }}
          </span>
          <span class="rt-run-time">{{ timeAgo(run.timestamp) }}</span>
        </button>
      </div>

      <div v-if="store.runs.length === 0" class="rt-empty">
        No runs yet. Run a comparison to start.
      </div>

      <!-- Compare result -->
      <div v-if="store.compareResult" class="rt-diff">
        <div class="rt-diff-title">
          #{{ store.compareResult.baseRun.runNumber }}
          vs
          #{{ store.compareResult.targetRun.runNumber }}
        </div>
        <div class="rt-diff-grid">
          <div class="rt-diff-row" :class="{ changed: store.compareResult.verdictChanged }">
            <span class="rt-diff-label">Verdict</span>
            <span class="rt-diff-val">{{ store.compareResult.targetVerdict || '(same)' }}</span>
          </div>
          <div class="rt-diff-row" :class="{ changed: store.compareResult.rootCauseChanged }">
            <span class="rt-diff-label">Root Cause</span>
            <span class="rt-diff-val">{{ store.compareResult.targetRootCause }}</span>
          </div>
          <div class="rt-diff-row" :class="{ changed: store.compareResult.divergenceMoved }">
            <span class="rt-diff-label">Divergence</span>
            <span class="rt-diff-val">{{ store.compareResult.targetDivergence }}</span>
          </div>
          <div class="rt-diff-row" :class="{ changed: store.compareResult.outputChanged }">
            <span class="rt-diff-label">Output B</span>
            <span class="rt-diff-val">{{ store.compareResult.targetOutputB || '(same)' }}</span>
          </div>
          <div class="rt-diff-row">
            <span class="rt-diff-label">Diagnosis</span>
            <span class="rt-diff-val">{{ store.compareResult.targetDiagnosis }}</span>
          </div>
          <div class="rt-diff-row nodes">
            <span class="rt-diff-label">Nodes</span>
            <span class="rt-diff-val" :class="diffClass(store.compareResult.nodeCountDiff)">
              {{ diffSign(store.compareResult.nodeCountDiff) }}
            </span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.run-timeline {
  width: 240px;
  min-width: 240px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: all 0.2s;
  max-height: calc(100vh - 300px);
}

.run-timeline.collapsed {
  width: 40px;
  min-width: 40px;
}

.rt-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid #f0f0f0;
  background: #fafbff;
  gap: 6px;
}

.rt-title {
  font-size: 12px;
  font-weight: 700;
  color: #303133;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  white-space: nowrap;
}

.rt-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.rt-compare-btn {
  padding: 2px 8px;
  border: 1px solid #d9ecff;
  background: #ecf5ff;
  color: #409EFF;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}

.rt-compare-btn:hover:not(:disabled) {
  background: #409EFF;
  color: #fff;
}

.rt-compare-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.rt-compare-btn.active {
  background: #E6A23C;
  color: #fff;
  border-color: #E6A23C;
}

.rt-toggle {
  padding: 2px 6px;
  border: none;
  background: transparent;
  color: #909399;
  font-size: 10px;
  cursor: pointer;
  border-radius: 4px;
}

.rt-toggle:hover {
  background: #ecf5ff;
  color: #409EFF;
}

.rt-compare-hint {
  padding: 6px 12px;
  font-size: 10px;
  color: #E6A23C;
  background: #fdf6ec;
  border-bottom: 1px solid #faecd8;
  text-align: center;
}

.rt-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-height: 0;
}

.rt-item {
  display: grid;
  grid-template-columns: auto 1fr auto;
  grid-template-rows: auto auto;
  gap: 0 6px;
  align-items: center;
  padding: 6px 8px;
  border: none;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
  border-left: 3px solid transparent;
}

.rt-item:hover {
  background: #f5f7fa;
}

.rt-item.active {
  background: #ecf5ff;
  border-left-color: #409EFF;
}

.rt-item.target {
  background: #ecf5ff;
  border-left-color: #409EFF;
}

.rt-item.baseline {
  background: #fdf6ec;
  border-left-color: #E6A23C;
}

.rt-item.baseline.target {
  background: #fdf6ec;
  border-left-color: #E6A23C;
}

.rt-run-num {
  grid-row: 1;
  grid-column: 1;
  font-size: 10px;
  font-weight: 700;
  color: #C0C4CC;
  font-variant-numeric: tabular-nums;
}

.rt-item.active .rt-run-num,
.rt-item.target .rt-run-num {
  color: #409EFF;
}

.rt-item.baseline .rt-run-num {
  color: #E6A23C;
}

.rt-run-label {
  grid-row: 1;
  grid-column: 2;
  font-size: 11px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rt-run-status {
  grid-row: 1;
  grid-column: 3;
  font-size: 10px;
  font-weight: 700;
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
}

.rt-run-status.err { background: #fef0f0; color: #F56C6C; }
.rt-run-status.warn { background: #fdf6ec; color: #E6A23C; }
.rt-run-status.ok { background: #f0f9eb; color: #67C23A; }

.rt-run-time {
  grid-row: 2;
  grid-column: 1 / -1;
  font-size: 9px;
  color: #C0C4CC;
}

.rt-empty {
  padding: 20px 12px;
  font-size: 11px;
  color: #C0C4CC;
  text-align: center;
  line-height: 1.6;
}

/* ── Diff panel ── */
.rt-diff {
  border-top: 2px solid #E6A23C;
  background: #fefefe;
  padding: 8px;
}

.rt-diff-title {
  font-size: 11px;
  font-weight: 700;
  color: #E6A23C;
  margin-bottom: 8px;
  text-align: center;
}

.rt-diff-grid {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.rt-diff-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
  padding: 3px 0;
  font-size: 10px;
}

.rt-diff-row:not(:last-child) {
  border-bottom: 1px solid #f5f5f5;
}

.rt-diff-label {
  color: #909399;
  font-weight: 600;
  flex-shrink: 0;
  text-transform: uppercase;
  font-size: 9px;
  min-width: 55px;
}

.rt-diff-val {
  color: #606266;
  text-align: right;
  word-break: break-all;
  line-height: 1.3;
}

.rt-diff-row.changed .rt-diff-val {
  color: #E6A23C;
  font-weight: 600;
}

.rt-diff-row.nodes .rt-diff-val {
  font-family: monospace;
  font-weight: 700;
}

.diff-pos { color: #F56C6C !important; }
.diff-neg { color: #67C23A !important; }

/* Scrollbar */
.rt-list::-webkit-scrollbar { width: 4px; }
.rt-list::-webkit-scrollbar-thumb { background: #e4e7ed; border-radius: 2px; }
</style>
