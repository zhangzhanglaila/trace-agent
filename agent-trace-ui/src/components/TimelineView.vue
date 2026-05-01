<script setup lang="ts">
import { computed } from 'vue'
import { useTraceStore } from '../store/traceStore'
import type { GraphNode } from '../types/trace'

const store = useTraceStore()

const nodes = computed(() => store.traceData?.graph.nodes ?? [])
const primaryRun = computed(() => store.traceData?.graph.primary_run ?? 'run_b')

// Group nodes by diverged / not
const timelineGroups = computed(() => {
  const before: GraphNode[] = []
  const after: GraphNode[] = []

  let crossed = false
  for (const node of nodes.value) {
    if (node.diverged && !crossed) crossed = true
    if (crossed) {
      after.push(node)
    } else {
      before.push(node)
    }
  }

  return { before, after }
})

function selectNode(node: GraphNode) {
  store.selectNode(node.id)
}

const typeColors: Record<string, string> = {
  llm: '#409EFF',
  tool: '#67C23A',
  branch: '#E6A23C',
  merge: '#909399',
  output: '#F56C6C',
  error: '#F56C6C',
}

const typeLabels: Record<string, string> = {
  llm: 'LLM',
  tool: 'Tool',
  branch: 'Branch',
  merge: 'Merge',
  output: 'Output',
  error: 'Error',
}
</script>

<template>
  <div class="timeline-view">
    <!-- Before divergence -->
    <div class="timeline-section">
      <div class="section-label">Normal Path</div>
      <div class="timeline-track">
        <div
          v-for="node in timelineGroups.before"
          :key="node.id"
          class="timeline-node"
          :class="{
            selected: store.selectedNodeId === node.id,
            'is-root-cause': node.is_root_cause,
          }"
          @click="selectNode(node)"
        >
          <div class="node-connector">
            <div class="dot" :style="{ background: typeColors[node.type] || '#909399' }"></div>
            <div class="line"></div>
          </div>
          <div class="node-card">
            <div class="node-card-header">
              <span class="node-type-badge" :style="{ background: typeColors[node.type] || '#909399' }">
                {{ typeLabels[node.type] || node.type }}
              </span>
              <span class="node-status" :class="node.status">
                {{ node.status === 'error' ? '❌' : node.status === 'success' ? '✅' : '⏳' }}
              </span>
              <span v-if="node.latency_ms" class="node-latency">{{ node.latency_ms.toFixed(0) }}ms</span>
            </div>
            <div class="node-name">{{ node.label }}</div>
            <div v-if="node.error" class="node-error">{{ node.error }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Divergence marker -->
    <div v-if="timelineGroups.after.length > 0" class="divergence-divider">
      <div class="divergence-line"></div>
      <div class="divergence-badge">⚠ DIVERGED</div>
      <div class="divergence-line"></div>
    </div>

    <!-- After divergence -->
    <div v-if="timelineGroups.after.length > 0" class="timeline-section">
      <div class="section-label diverged-label">Diverged Path ({{ primaryRun === 'run_b' ? 'Run B' : 'Run A' }})</div>
      <div class="timeline-track">
        <div
          v-for="node in timelineGroups.after"
          :key="node.id"
          class="timeline-node diverged-node"
          :class="{
            selected: store.selectedNodeId === node.id,
            'is-root-cause': node.is_root_cause,
            'is-divergence-point': node.is_divergence_point,
          }"
          @click="selectNode(node)"
        >
          <div class="node-connector">
            <div
              class="dot"
              :style="{
                background: node.is_root_cause ? '#F56C6C' : (typeColors[node.type] || '#F56C6C'),
                boxShadow: node.is_root_cause ? '0 0 12px rgba(245,108,108,0.6)' : 'none',
              }"
            ></div>
            <div class="line diverged-line"></div>
          </div>
          <div class="node-card diverged-card">
            <div class="node-card-header">
              <span class="node-type-badge" :style="{ background: typeColors[node.type] || '#F56C6C' }">
                {{ typeLabels[node.type] || node.type }}
              </span>
              <span class="node-status" :class="node.status">
                {{ node.status === 'error' ? '❌' : node.status === 'success' ? '✅' : '⏳' }}
              </span>
              <span v-if="node.latency_ms" class="node-latency">{{ node.latency_ms.toFixed(0) }}ms</span>
            </div>
            <div class="node-name">{{ node.label }}</div>
            <div v-if="node.error" class="node-error">{{ node.error }}</div>
            <div v-if="node.is_root_cause" class="root-cause-tag">🔴 ROOT CAUSE</div>
            <div v-if="node.is_divergence_point && !node.is_root_cause" class="div-point-tag">⬆ First divergence</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.timeline-view {
  padding: 8px 4px;
}

.timeline-section {
  margin-bottom: 4px;
}

.section-label {
  font-size: 11px;
  font-weight: 600;
  color: #67C23A;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 0 16px;
  margin-bottom: 8px;
}

.section-label.diverged-label {
  color: #F56C6C;
}

.timeline-track {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.timeline-node {
  display: flex;
  align-items: stretch;
  cursor: pointer;
  border-radius: 8px;
  transition: background 0.15s;
  padding: 2px 0;
}

.timeline-node:hover {
  background: #f5f7fa;
}

.timeline-node.selected {
  background: #ecf5ff;
}

.timeline-node.is-root-cause {
  background: #fef0f0;
}

/* ── Connector ── */
.node-connector {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 32px;
  flex-shrink: 0;
  padding-top: 12px;
}

.dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px rgba(0,0,0,0.1);
  z-index: 1;
  flex-shrink: 0;
}

.line {
  width: 2px;
  flex: 1;
  background: #e4e7ed;
  margin-top: 2px;
  min-height: 8px;
}

.line.diverged-line {
  background: repeating-linear-gradient(
    to bottom,
    #F56C6C 0px,
    #F56C6C 3px,
    transparent 3px,
    transparent 6px
  );
}

/* ── Card ── */
.node-card {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  margin: 2px 0;
  background: #fff;
  min-width: 0;
}

.diverged-card {
  border-left: 3px solid #F56C6C;
}

.node-card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 3px;
}

.node-type-badge {
  font-size: 10px;
  color: #fff;
  padding: 1px 6px;
  border-radius: 3px;
  font-weight: 600;
  text-transform: uppercase;
}

.node-status {
  font-size: 12px;
}

.node-latency {
  margin-left: auto;
  font-size: 10px;
  color: #C0C4CC;
}

.node-name {
  font-size: 12px;
  color: #303133;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-error {
  font-size: 11px;
  color: #F56C6C;
  margin-top: 2px;
}

.root-cause-tag {
  font-size: 10px;
  color: #F56C6C;
  font-weight: 700;
  margin-top: 4px;
  animation: pulse-text 1.5s ease-in-out infinite;
}

.div-point-tag {
  font-size: 10px;
  color: #E6A23C;
  font-weight: 600;
  margin-top: 4px;
}

@keyframes pulse-text {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* ── Divergence divider ── */
.divergence-divider {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 0;
  padding: 0 16px;
}

.divergence-line {
  flex: 1;
  height: 1px;
  background: #E6A23C;
  opacity: 0.5;
}

.divergence-badge {
  background: #fdf6ec;
  color: #E6A23C;
  border: 1px solid #E6A23C;
  padding: 4px 14px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}
</style>
