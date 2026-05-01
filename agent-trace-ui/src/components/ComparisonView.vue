<script setup lang="ts">
import { computed } from 'vue'
import { useTraceStore } from '../store/traceStore'
import type { GraphNode } from '../types/trace'

const store = useTraceStore()

const nodes = computed(() => store.traceData?.graph.nodes ?? [])
const secondaryNodes = computed(() => store.traceData?.graph.secondary_nodes ?? [])
const primaryRun = computed(() => store.traceData?.graph.primary_run ?? 'run_b')
const pathImpact = computed(() => store.traceData?.diff.path_impact ?? [])
const firstDiv = computed(() => store.traceData?.diff.first_divergence ?? null)

// Pair up nodes by path index
const pairedSteps = computed(() => {
  const pairs: Array<{
    index: number
    runA: GraphNode | null
    runB: GraphNode | null
    diverged: boolean
    isFirstDiv: boolean
  }> = []

  const impact = pathImpact.value
  const primaryNodes = nodes.value
  const secNodes = secondaryNodes.value

  // Determine which is run A and which is run B
  const isPrimaryB = primaryRun.value === 'run_b'
  const runANodes = isPrimaryB ? secNodes : primaryNodes
  const runBNodes = isPrimaryB ? primaryNodes : secNodes

  const maxLen = Math.max(runANodes.length, runBNodes.length)

  for (let i = 0; i < maxLen; i++) {
    const a = i < runANodes.length ? runANodes[i] : null
    const b = i < runBNodes.length ? runBNodes[i] : null
    const diverged = impact[i]?.diverged ?? false
    const isFirstDiv = diverged && !pairs.some(p => p.diverged)

    pairs.push({ index: i, runA: a, runB: b, diverged, isFirstDiv })
  }

  return pairs
})

function selectNode(nodeId: string | null) {
  store.selectNode(nodeId)
}

const typeColors: Record<string, string> = {
  llm: '#409EFF', tool: '#67C23A', branch: '#E6A23C',
  merge: '#909399', output: '#F56C6C', error: '#F56C6C',
}

// typeLabels kept for future use in tooltip/detail views
</script>

<template>
  <div class="comparison-view">
    <!-- Header -->
    <div class="compare-header">
      <div class="col-header col-a">Run A</div>
      <div class="col-header col-center">
        <span v-if="firstDiv" class="diff-badge">← diff →</span>
      </div>
      <div class="col-header col-b">Run B</div>
    </div>

    <!-- Paired steps -->
    <div class="compare-body">
      <div
        v-for="pair in pairedSteps"
        :key="pair.index"
        class="compare-row"
        :class="{
          diverged: pair.diverged,
          'first-div': pair.isFirstDiv,
        }"
      >
        <!-- Run A -->
        <div
          class="compare-cell cell-a"
          :class="{
            'has-node': pair.runA,
            selected: store.selectedNodeId === pair.runA?.id,
          }"
          @click="selectNode(pair.runA?.id ?? null)"
        >
          <template v-if="pair.runA">
            <span class="cell-dot" :style="{ background: typeColors[pair.runA.type] || '#909399' }"></span>
            <span class="cell-label">{{ pair.runA.label }}</span>
            <span class="cell-status" :class="pair.runA.status">
              {{ pair.runA.status === 'error' ? '❌' : '✅' }}
            </span>
          </template>
          <span v-else class="cell-empty">—</span>
        </div>

        <!-- Center: diff marker -->
        <div class="compare-cell cell-center">
          <span v-if="pair.isFirstDiv" class="diverge-arrow">⟵</span>
          <span v-else-if="pair.diverged" class="diverge-dot">•</span>
          <span v-else class="diverge-none">=</span>
        </div>

        <!-- Run B -->
        <div
          class="compare-cell cell-b"
          :class="{
            'has-node': pair.runB,
            selected: store.selectedNodeId === pair.runB?.id,
            'is-bad': pair.runB?.status === 'error',
          }"
          @click="selectNode(pair.runB?.id ?? null)"
        >
          <template v-if="pair.runB">
            <span class="cell-dot" :style="{ background: pair.runB?.status === 'error' ? '#F56C6C' : (typeColors[pair.runB?.type] || '#909399') }"></span>
            <span class="cell-label">{{ pair.runB.label }}</span>
            <span class="cell-status" :class="pair.runB.status">
              {{ pair.runB.status === 'error' ? '❌' : '✅' }}
            </span>
            <span v-if="pair.runB.is_root_cause" class="root-marker">🔴</span>
          </template>
          <span v-else class="cell-empty">—</span>
        </div>
      </div>
    </div>

    <!-- Legend -->
    <div class="compare-footer">
      <span class="footer-note">= identical · • diverged · ⟵ first divergence</span>
    </div>
  </div>
</template>

<style scoped>
.comparison-view {
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
}

.compare-header {
  display: grid;
  grid-template-columns: 1fr 60px 1fr;
  background: #f5f7fa;
  border-bottom: 1px solid #e4e7ed;
}

.col-header {
  padding: 10px 16px;
  font-size: 13px;
  font-weight: 700;
}

.col-a { color: #67C23A; }
.col-b { color: #409EFF; }

.col-center {
  display: flex;
  align-items: center;
  justify-content: center;
  border-left: 1px solid #e4e7ed;
  border-right: 1px solid #e4e7ed;
}

.diff-badge {
  font-size: 10px;
  color: #E6A23C;
  font-weight: 600;
  white-space: nowrap;
}

.compare-body {
  display: flex;
  flex-direction: column;
  max-height: 500px;
  overflow-y: auto;
}

.compare-row {
  display: grid;
  grid-template-columns: 1fr 60px 1fr;
  border-bottom: 1px solid #f5f7fa;
  transition: background 0.15s;
  min-height: 44px;
}

.compare-row:hover { background: #fafafa; }
.compare-row.diverged { background: #fef0f0; }
.compare-row.first-div { background: #fdf6ec; border: 1px dashed #E6A23C; }

.compare-cell {
  padding: 8px 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  cursor: pointer;
  min-width: 0;
}

.compare-cell.selected { background: #ecf5ff; }

.compare-cell.cell-center {
  justify-content: center;
  border-left: 1px solid #f0f0f0;
  border-right: 1px solid #f0f0f0;
  cursor: default;
}

.cell-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.cell-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #303133;
}

.cell-status { font-size: 12px; }

.cell-empty {
  color: #C0C4CC;
  justify-content: center;
}

.diverge-arrow {
  color: #E6A23C;
  font-size: 16px;
  font-weight: 700;
  animation: pulse 1.5s ease-in-out infinite;
}

.diverge-dot { color: #F56C6C; font-size: 18px; font-weight: 700; }
.diverge-none { color: #C0C4CC; font-size: 14px; }

.root-marker { font-size: 12px; animation: pulse 1s ease-in-out infinite; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.is-bad .cell-label { color: #F56C6C; font-weight: 600; }

.compare-footer {
  padding: 8px 16px;
  background: #fafafa;
  border-top: 1px solid #f0f0f0;
}

.footer-note {
  font-size: 11px;
  color: #C0C4CC;
}
</style>
