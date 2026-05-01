<script setup lang="ts">
import { computed } from 'vue'
import { useTraceStore } from '../store/traceStore'

const store = useTraceStore()
const collapsed = defineModel<boolean>('collapsed', { default: false })

const visibleRuns = computed(() => store.runs.slice(0, 50))

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
</script>

<template>
  <div class="run-timeline" :class="{ collapsed }">
    <div class="rt-header">
      <span class="rt-title" v-if="!collapsed">Runs</span>
      <button class="rt-toggle" @click="collapsed = !collapsed">
        {{ collapsed ? '▶' : '◀' }}
      </button>
    </div>

    <template v-if="!collapsed">
      <div class="rt-list">
        <button
          v-for="run in visibleRuns"
          :key="run.id"
          class="rt-item"
          :class="{ active: run.id === store.activeRunId }"
          @click="store.loadRun(run.id)"
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
        No runs yet.
        <br />
        Run a comparison to start.
      </div>
    </template>
  </div>
</template>

<style scoped>
.run-timeline {
  width: 220px;
  min-width: 220px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: all 0.2s;
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
  gap: 4px;
}

.rt-title {
  font-size: 12px;
  font-weight: 700;
  color: #303133;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  white-space: nowrap;
}

.rt-toggle {
  padding: 2px 6px;
  border: none;
  background: transparent;
  color: #909399;
  font-size: 10px;
  cursor: pointer;
  border-radius: 4px;
  flex-shrink: 0;
}

.rt-toggle:hover {
  background: #ecf5ff;
  color: #409EFF;
}

.rt-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
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
}

.rt-item:hover {
  background: #f5f7fa;
}

.rt-item.active {
  background: #ecf5ff;
  box-shadow: inset 3px 0 0 #409EFF;
}

.rt-run-num {
  grid-row: 1;
  grid-column: 1;
  font-size: 10px;
  font-weight: 700;
  color: #C0C4CC;
  font-variant-numeric: tabular-nums;
}

.rt-item.active .rt-run-num {
  color: #409EFF;
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

.rt-run-status.err {
  background: #fef0f0;
  color: #F56C6C;
}

.rt-run-status.warn {
  background: #fdf6ec;
  color: #E6A23C;
}

.rt-run-status.ok {
  background: #f0f9eb;
  color: #67C23A;
}

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

/* Scrollbar */
.rt-list::-webkit-scrollbar {
  width: 4px;
}

.rt-list::-webkit-scrollbar-thumb {
  background: #e4e7ed;
  border-radius: 2px;
}
</style>
