<script setup lang="ts">
import { computed } from 'vue'
import { useTraceStore } from '../store/traceStore'

const store = useTraceStore()

const diff = computed(() => store.traceData?.diff ?? null)
const rootCause = computed(() => store.traceData?.root_cause ?? null)
const output = computed(() => store.traceData?.output ?? null)

const firstDiv = computed(() => diff.value?.first_divergence ?? null)
const pathImpact = computed(() => diff.value?.path_impact ?? [])

const firstDivergedIndex = computed(() => {
  const first = pathImpact.value.find(p => p.diverged)
  return first?.index ?? -1
})
</script>

<template>
  <div class="diff-panel">
    <h3>Diff Analysis</h3>

    <!-- First Divergence -->
    <div v-if="firstDiv" class="first-divergence">
      <div class="div-label">First Divergence</div>
      <div class="div-desc">{{ firstDiv.description }}</div>
      <div class="div-values" v-if="firstDiv.run_a || firstDiv.run_b">
        <div class="div-val div-val-a" v-if="firstDiv.run_a">
          <span class="val-label">Run A:</span>
          <code>{{ firstDiv.run_a }}</code>
        </div>
        <div class="div-val div-val-b" v-if="firstDiv.run_b">
          <span class="val-label">Run B:</span>
          <code>{{ firstDiv.run_b }}</code>
        </div>
      </div>
    </div>

    <!-- Root Cause Variable -->
    <div v-if="rootCause?.variable" class="variable-diff">
      <div class="div-label">Variable Diff</div>
      <div class="var-row">
        <code class="var-name">{{ rootCause.variable }}</code>
        <span class="var-source">{{ rootCause.source }}</span>
      </div>
      <div class="var-values">
        <div class="var-val var-val-a">
          <div class="val-label">Run A</div>
          <code>{{ rootCause.run_a }}</code>
        </div>
        <div class="var-val var-val-b">
          <div class="val-label">Run B</div>
          <code>{{ rootCause.run_b }}</code>
        </div>
      </div>
    </div>

    <!-- Path Impact (Cascade) -->
    <div class="path-impact">
      <div class="div-label">Path Cascade</div>
      <div class="cascade-list">
        <div
          v-for="step in pathImpact"
          :key="step.index"
          class="cascade-row"
          :class="{ diverged: step.diverged, 'divergence-start': step.index === firstDivergedIndex }"
        >
          <span class="cascade-idx">{{ step.index }}</span>
          <span class="cascade-a">{{ step.run_a || '—' }}</span>
          <span class="cascade-b">{{ step.run_b || '—' }}</span>
          <span v-if="step.index === firstDivergedIndex" class="diverge-marker">⟵ DIVERGED</span>
        </div>
      </div>
    </div>

    <!-- Output Comparison -->
    <div v-if="output" class="output-compare">
      <div class="div-label">Output</div>
      <div class="output-row output-a" :class="{ 'is-bad': output.diverged }">
        <span class="out-label">Run A</span>
        <span class="out-text">{{ output.run_a.slice(0, 120) }}</span>
      </div>
      <div class="output-row output-b" :class="{ 'is-bad': output.diverged }">
        <span class="out-label">Run B</span>
        <span class="out-text">{{ output.run_b.slice(0, 120) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.diff-panel {
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  max-height: 100%;
  overflow-y: auto;
}

.diff-panel h3 {
  margin: 0 0 14px 0;
  font-size: 15px;
  color: #303133;
}

.div-label {
  font-size: 11px;
  font-weight: 600;
  color: #909399;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}

.first-divergence {
  margin-bottom: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid #f0f0f0;
}

.div-desc {
  font-size: 13px;
  color: #E6A23C;
  font-weight: 500;
  margin-bottom: 8px;
}

.div-values {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.div-val {
  font-size: 12px;
}

.val-label {
  color: #909399;
  font-weight: 600;
  margin-right: 6px;
}

.div-val-a code { background: #f0f9eb; color: #67C23A; padding: 2px 6px; border-radius: 3px; font-size: 12px; }
.div-val-b code { background: #fef0f0; color: #F56C6C; padding: 2px 6px; border-radius: 3px; font-size: 12px; }

/* ── Variable Diff ── */
.variable-diff {
  margin-bottom: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid #f0f0f0;
}

.var-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.var-name {
  background: #ecf5ff;
  color: #409EFF;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 700;
  font-size: 13px;
}

.var-source {
  font-size: 11px;
  color: #C0C4CC;
}

.var-values {
  display: flex;
  gap: 12px;
}

.var-val {
  flex: 1;
  background: #fafafa;
  border-radius: 6px;
  padding: 8px;
}

.var-val-a { border-left: 3px solid #67C23A; }
.var-val-b { border-left: 3px solid #F56C6C; }

.var-val .val-label {
  display: block;
  font-size: 10px;
  color: #909399;
  margin-bottom: 4px;
  text-transform: uppercase;
}

.var-val code {
  font-size: 13px;
  font-weight: 600;
}

.var-val-a code { color: #67C23A; }
.var-val-b code { color: #F56C6C; }

/* ── Path Cascade ── */
.path-impact {
  margin-bottom: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid #f0f0f0;
}

.cascade-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cascade-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 6px;
  border-radius: 4px;
  font-size: 12px;
  font-family: monospace;
  transition: background 0.2s;
}

.cascade-row:hover {
  background: #f5f7fa;
}

.cascade-row.diverged {
  background: #fef0f0;
}

.cascade-row.divergence-start {
  background: #fdf6ec;
  border: 1px dashed #E6A23C;
}

.cascade-idx {
  color: #C0C4CC;
  width: 20px;
  text-align: right;
  flex-shrink: 0;
}

.cascade-a {
  color: #67C23A;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cascade-b {
  color: #F56C6C;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diverge-marker {
  color: #E6A23C;
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* ── Output ── */
.output-compare {
  margin-bottom: 8px;
}

.output-row {
  padding: 8px;
  border-radius: 4px;
  margin-bottom: 6px;
  font-size: 12px;
}

.output-a {
  background: #f0f9eb;
  border-left: 3px solid #67C23A;
}

.output-b {
  background: #fef0f0;
  border-left: 3px solid #F56C6C;
}

.out-label {
  font-weight: 700;
  margin-right: 6px;
  display: block;
  margin-bottom: 2px;
}

.out-text {
  color: #606266;
  word-break: break-all;
}
</style>
