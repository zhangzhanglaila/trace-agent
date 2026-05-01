<script setup lang="ts">
import { computed } from 'vue'
import { useTraceStore } from '../store/traceStore'

const store = useTraceStore()

const verdictText = computed(() => store.traceData?.verdict ?? '')
const diagnosis = computed(() => store.traceData?.diagnosis ?? null)
const hasError = computed(() => store.hasError)
const rootCause = computed(() => store.traceData?.root_cause ?? null)

const statusColor = computed(() => hasError.value ? '#F56C6C' : '#67C23A')
const statusIcon = computed(() => hasError.value ? '❌' : '✅')
const statusLabel = computed(() => hasError.value ? 'Run B Failed' : 'Both Runs OK')

const confidenceColor = computed(() => {
  const c = diagnosis.value?.confidence ?? ''
  if (c === 'High') return '#F56C6C'
  if (c === 'Medium') return '#E6A23C'
  return '#909399'
})
</script>

<template>
  <div class="verdict-card" :style="{ borderLeftColor: statusColor }">
    <div class="verdict-header">
      <span class="verdict-icon">{{ statusIcon }}</span>
      <span class="verdict-status" :style="{ color: statusColor }">{{ statusLabel }}</span>
      <span v-if="diagnosis" class="diagnosis-badge" :style="{ background: confidenceColor }">
        {{ diagnosis.type }}
        <span class="confidence">({{ diagnosis.confidence }})</span>
      </span>
      <span v-if="diagnosis" class="category-tag">{{ diagnosis.category }}</span>
    </div>

    <p class="verdict-text">{{ verdictText }}</p>

    <div v-if="rootCause && rootCause.variable" class="root-cause-inline">
      <span class="rc-label">Root Cause:</span>
      <code class="rc-var">{{ rootCause.variable }}</code>
      <span class="rc-arrow">=</span>
      <code class="rc-val rc-val-a">{{ rootCause.run_a }}</code>
      <span class="rc-vs">vs</span>
      <code class="rc-val rc-val-b">{{ rootCause.run_b }}</code>
    </div>
  </div>
</template>

<style scoped>
.verdict-card {
  background: #fff;
  border-left: 4px solid #67C23A;
  border-radius: 8px;
  padding: 20px 24px;
  margin-bottom: 16px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.verdict-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.verdict-icon {
  font-size: 20px;
}

.verdict-status {
  font-size: 16px;
  font-weight: 700;
}

.diagnosis-badge {
  color: #fff;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 600;
}

.confidence {
  opacity: 0.85;
  font-weight: 400;
}

.category-tag {
  background: #f0f2f5;
  color: #606266;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  border: 1px solid #e4e7ed;
}

.verdict-text {
  font-size: 17px;
  line-height: 1.6;
  color: #303133;
  margin: 0 0 12px 0;
  font-weight: 500;
}

.root-cause-inline {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 14px;
  color: #606266;
  background: #fafafa;
  padding: 8px 12px;
  border-radius: 6px;
}

.rc-label {
  font-weight: 600;
  color: #303133;
}

.rc-var {
  background: #ecf5ff;
  color: #409EFF;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.rc-arrow {
  color: #909399;
}

.rc-val {
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 13px;
}

.rc-val-a {
  background: #f0f9eb;
  color: #67C23A;
}

.rc-vs {
  color: #C0C4CC;
  font-weight: 600;
}

.rc-val-b {
  background: #fef0f0;
  color: #F56C6C;
}
</style>
