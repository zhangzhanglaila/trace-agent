<script setup lang="ts">
import { computed } from 'vue'
import { useTraceStore } from '../store/traceStore'

const store = useTraceStore()
const node = computed(() => store.selectedNode)

const inputEntries = computed(() => {
  if (!node.value?.inputs) return []
  return Object.entries(node.value.inputs).filter(([k]) => k !== '_value')
})

const outputEntries = computed(() => {
  if (!node.value?.outputs) return []
  return Object.entries(node.value.outputs).filter(([k]) => k !== '_value')
})
</script>

<template>
  <div class="step-detail" v-if="node">
    <div class="detail-header">
      <h3>
        <span class="node-type-dot" :class="'dot-' + node.type"></span>
        {{ node.name }}
      </h3>
      <span class="node-type-tag" :class="'tag-' + node.type">{{ node.type }}</span>
    </div>

    <div class="detail-status" :class="'status-' + node.status">
      <span class="status-icon">{{ node.status === 'error' ? '❌' : node.status === 'success' ? '✅' : '⏳' }}</span>
      {{ node.status }}
      <span v-if="node.latency_ms" class="latency">{{ node.latency_ms.toFixed(1) }}ms</span>
    </div>

    <div v-if="node.is_root_cause" class="root-cause-badge">
      🔴 ROOT CAUSE — {{ store.traceData?.root_cause?.variable }} diverged here
    </div>

    <div v-if="node.is_divergence_point" class="divergence-badge">
      ⚠ DIVERGENCE POINT
    </div>

    <!-- Inputs -->
    <div class="detail-section" v-if="inputEntries.length > 0">
      <div class="section-title">Inputs</div>
      <div class="kv-list">
        <div v-for="[key, val] in inputEntries" :key="key" class="kv-row">
          <span class="kv-key">{{ key }}</span>
          <code class="kv-val">{{ typeof val === 'object' ? JSON.stringify(val).slice(0, 120) : String(val).slice(0, 120) }}</code>
        </div>
      </div>
    </div>

    <!-- Outputs -->
    <div class="detail-section" v-if="outputEntries.length > 0">
      <div class="section-title">Outputs</div>
      <div class="kv-list">
        <div v-for="[key, val] in outputEntries" :key="key" class="kv-row">
          <span class="kv-key">{{ key }}</span>
          <code class="kv-val">{{ typeof val === 'object' ? JSON.stringify(val).slice(0, 120) : String(val).slice(0, 120) }}</code>
        </div>
      </div>
    </div>

    <!-- Error -->
    <div class="detail-section error-section" v-if="node.error">
      <div class="section-title">Error</div>
      <div class="error-text">{{ node.error }}</div>
    </div>

    <!-- Empty state -->
    <div v-if="inputEntries.length === 0 && outputEntries.length === 0 && !node.error" class="empty-state">
      <p>No input/output data recorded for this step.</p>
    </div>
  </div>

  <div class="step-detail empty" v-else>
    <div class="empty-state">
      <div class="empty-icon">👆</div>
      <p>Click a node in the graph to inspect its inputs, outputs, and status.</p>
    </div>
  </div>
</template>

<style scoped>
.step-detail {
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  max-height: 100%;
  overflow-y: auto;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.detail-header h3 {
  margin: 0;
  font-size: 15px;
  color: #303133;
  display: flex;
  align-items: center;
  gap: 8px;
}

.node-type-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.dot-llm { background: #409EFF; }
.dot-tool { background: #67C23A; }
.dot-branch { background: #E6A23C; }
.dot-merge { background: #909399; }
.dot-output { background: #F56C6C; }
.dot-error { background: #F56C6C; }

.node-type-tag {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 600;
  text-transform: uppercase;
}

.tag-llm { background: #ecf5ff; color: #409EFF; }
.tag-tool { background: #f0f9eb; color: #67C23A; }
.tag-branch { background: #fdf6ec; color: #E6A23C; }
.tag-merge { background: #f4f4f5; color: #909399; }
.tag-output { background: #fef0f0; color: #F56C6C; }
.tag-error { background: #fef0f0; color: #F56C6C; }

.detail-status {
  font-size: 13px;
  font-weight: 600;
  padding: 6px 10px;
  border-radius: 4px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-success { background: #f0f9eb; color: #67C23A; }
.status-error { background: #fef0f0; color: #F56C6C; }
.status-pending { background: #f5f7fa; color: #909399; }

.latency {
  margin-left: auto;
  font-weight: 400;
  font-size: 12px;
  color: #909399;
}

.root-cause-badge {
  background: #fef0f0;
  border: 1px solid #F56C6C;
  color: #F56C6C;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 12px;
  animation: pulse-border 2s ease-in-out infinite;
}

.divergence-badge {
  background: #fdf6ec;
  border: 1px solid #E6A23C;
  color: #E6A23C;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 12px;
}

@keyframes pulse-border {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245, 108, 108, 0.4); }
  50% { box-shadow: 0 0 0 6px rgba(245, 108, 108, 0); }
}

.detail-section {
  margin-bottom: 14px;
}

.section-title {
  font-size: 11px;
  font-weight: 600;
  color: #909399;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}

.kv-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.kv-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
}

.kv-key {
  font-weight: 600;
  color: #606266;
  min-width: 80px;
  flex-shrink: 0;
}

.kv-val {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 11px;
  color: #303133;
  word-break: break-all;
  max-height: 60px;
  overflow-y: auto;
}

.error-section {
  background: #fef0f0;
  border-radius: 6px;
  padding: 8px;
}

.error-text {
  color: #F56C6C;
  font-size: 12px;
  font-weight: 500;
}

.empty-state {
  text-align: center;
  padding: 32px 16px;
  color: #909399;
}

.empty-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

.empty-state p {
  font-size: 13px;
  line-height: 1.5;
  margin: 0;
}
</style>
