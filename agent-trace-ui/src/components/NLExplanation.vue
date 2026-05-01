<script setup lang="ts">
import { computed } from 'vue'
import { useTraceStore } from '../store/traceStore'

const store = useTraceStore()

const explanation = computed(() => store.explanationText)
const hasError = computed(() => store.hasError)
const diagnosis = computed(() => store.traceData?.diagnosis ?? null)
const firstDivergence = computed(() => store.traceData?.diff.first_divergence ?? null)

const statusColor = computed(() => hasError.value ? '#F56C6C' : '#67C23A')
const statusEmoji = computed(() => hasError.value ? '🔴' : '🟢')
</script>

<template>
  <div class="nl-explanation" :style="{ borderColor: statusColor }">
    <div class="nl-header">
      <span class="nl-emoji">{{ statusEmoji }}</span>
      <span class="nl-title" :style="{ color: statusColor }">
        {{ hasError ? 'Why did Run B fail?' : 'Why are the runs identical?' }}
      </span>
    </div>

    <p class="nl-text">{{ explanation }}</p>

    <div v-if="firstDivergence && hasError" class="nl-detail">
      <div class="nl-detail-row">
        <span class="nl-detail-label">First Divergence:</span>
        <span class="nl-detail-value">{{ firstDivergence.description }}</span>
      </div>
      <div class="nl-detail-row" v-if="firstDivergence.run_a || firstDivergence.run_b">
        <span class="nl-detail-label">Values:</span>
        <code class="nl-val-a" v-if="firstDivergence.run_a">Run A: {{ firstDivergence.run_a }}</code>
        <code class="nl-val-b" v-if="firstDivergence.run_b">Run B: {{ firstDivergence.run_b }}</code>
      </div>
    </div>

    <div v-if="diagnosis" class="nl-tags">
      <span class="nl-tag nl-tag-type">{{ diagnosis.type }}</span>
      <span class="nl-tag nl-tag-confidence">{{ diagnosis.confidence }} confidence</span>
      <span class="nl-tag nl-tag-category">{{ diagnosis.category }}</span>
    </div>
  </div>
</template>

<style scoped>
.nl-explanation {
  background: #fff;
  border-left: 4px solid #F56C6C;
  border-radius: 8px;
  padding: 16px 20px;
  margin-bottom: 12px;
  box-shadow: 0 1px 8px rgba(0, 0, 0, 0.04);
}

.nl-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.nl-emoji {
  font-size: 16px;
}

.nl-title {
  font-size: 15px;
  font-weight: 700;
}

.nl-text {
  font-size: 15px;
  line-height: 1.7;
  color: #303133;
  margin: 0 0 12px 0;
  font-weight: 500;
}

.nl-detail {
  background: #fafafa;
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 10px;
}

.nl-detail-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  flex-wrap: wrap;
}

.nl-detail-row + .nl-detail-row {
  margin-top: 6px;
}

.nl-detail-label {
  font-weight: 600;
  color: #606266;
}

.nl-detail-value {
  color: #303133;
}

.nl-val-a {
  background: #f0f9eb;
  color: #67C23A;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
}

.nl-val-b {
  background: #fef0f0;
  color: #F56C6C;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
}

.nl-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.nl-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 600;
}

.nl-tag-type {
  background: #fef0f0;
  color: #F56C6C;
  border: 1px solid #fde2e2;
}

.nl-tag-confidence {
  background: #fdf6ec;
  color: #E6A23C;
  border: 1px solid #faecd8;
}

.nl-tag-category {
  background: #f0f2f5;
  color: #909399;
  border: 1px solid #e4e7ed;
}
</style>
