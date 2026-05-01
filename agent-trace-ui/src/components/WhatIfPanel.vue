<script setup lang="ts">
import { computed } from 'vue'
import { useTraceStore } from '../store/traceStore'

const store = useTraceStore()

const rootCause = computed(() => store.traceData?.root_cause ?? null)
const whatIfData = computed(() => store.whatIfData)
const whatIfLoading = computed(() => store.whatIfLoading)
const whatIfError = computed(() => store.whatIfError)
const hasError = computed(() => store.hasError)

const outputA = computed(() => store.traceData?.output.run_a ?? '')
const outputB = computed(() => store.traceData?.output.run_b ?? '')
const outputC = computed(() => whatIfData.value?.run_c_output ?? '')
const wouldFix = computed(() => whatIfData.value?.would_fix ?? false)
const fixDesc = computed(() => whatIfData.value?.fix_description ?? '')

const runCSteps = computed(() => whatIfData.value?.run_c_trace?.steps ?? 0)
const runCId = computed(() => whatIfData.value?.run_c_trace?.trace_id ?? '')

async function runWhatIf() {
  await store.fetchWhatIf()
}
</script>

<template>
  <div class="whatif-panel" v-if="hasError">
    <div class="whatif-header">
      <span class="whatif-icon">🔄</span>
      <span class="whatif-title">What-If Replay</span>
      <span class="whatif-subtitle">Counterfactual: what if the bug were fixed?</span>
    </div>

    <!-- Pre-execution state -->
    <div v-if="!whatIfData && !whatIfLoading && !whatIfError" class="whatif-prompt">
      <p class="whatif-desc">
        Click "Try Fix" to generate a counterfactual Run C where
        <code class="whatif-var">{{ rootCause?.run_a || 'the correct tool' }}</code>
        is used instead of
        <code class="whatif-var-err">{{ rootCause?.run_b || 'the wrong tool' }}</code>
        at the decision point.
      </p>
      <button class="whatif-btn" @click="runWhatIf" :disabled="whatIfLoading">
        🔧 Try Fix — Generate Run C
      </button>
    </div>

    <!-- Loading -->
    <div v-if="whatIfLoading" class="whatif-loading">
      <div class="whatif-spinner"></div>
      <p>Running counterfactual analysis...</p>
      <p class="whatif-loading-detail">This reruns the full agent pipeline with the bug disabled.</p>
    </div>

    <!-- Error -->
    <div v-if="whatIfError" class="whatif-error">
      <p>❌ {{ whatIfError }}</p>
      <button class="whatif-btn" @click="runWhatIf">Retry</button>
    </div>

    <!-- Results: three-way comparison -->
    <div v-if="whatIfData && !whatIfLoading" class="whatif-result">
      <!-- Verdict -->
      <div class="whatif-verdict" :class="{ fixed: wouldFix, unfixed: !wouldFix }">
        <span v-if="wouldFix">✅ The fix would resolve the issue</span>
        <span v-else>⚠ The fix may not fully resolve the issue</span>
      </div>

      <!-- Three-way output comparison -->
      <div class="whatif-three-way">
        <div class="whatif-col whatif-col-a">
          <div class="whatif-col-header col-a">Run A (Tokyo — correct)</div>
          <div class="whatif-col-body">
            <code>{{ outputA }}</code>
          </div>
        </div>
        <div class="whatif-col whatif-col-b">
          <div class="whatif-col-header col-b">Run B (Paris — buggy)</div>
          <div class="whatif-col-body">
            <code>{{ outputB }}</code>
          </div>
        </div>
        <div class="whatif-col whatif-col-c">
          <div class="whatif-col-header col-c">Run C (Paris — fixed)</div>
          <div class="whatif-col-body">
            <code>{{ outputC }}</code>
          </div>
          <div class="whatif-col-meta">
            {{ runCSteps }} steps · trace: {{ runCId }}
          </div>
        </div>
      </div>

      <!-- Fix description -->
      <div v-if="fixDesc" class="whatif-fix-desc">
        <span class="whatif-fix-icon">💡</span>
        {{ fixDesc }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.whatif-panel {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
  margin-top: 12px;
}

.whatif-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: #fafafa;
  border-bottom: 1px solid #f0f0f0;
}

.whatif-icon {
  font-size: 16px;
}

.whatif-title {
  font-size: 14px;
  font-weight: 700;
  color: #303133;
}

.whatif-subtitle {
  font-size: 12px;
  color: #909399;
  margin-left: auto;
}

/* ── Prompt ── */
.whatif-prompt {
  padding: 16px;
}

.whatif-desc {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  margin: 0 0 12px 0;
}

.whatif-var {
  background: #f0f9eb;
  color: #67C23A;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.whatif-var-err {
  background: #fef0f0;
  color: #F56C6C;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.whatif-btn {
  padding: 10px 22px;
  background: linear-gradient(135deg, #409EFF, #337ecc);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.3);
  width: 100%;
}

.whatif-btn:hover {
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.4);
  transform: translateY(-1px);
}

.whatif-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
}

/* ── Loading ── */
.whatif-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px;
  gap: 8px;
  color: #909399;
  font-size: 13px;
}

.whatif-spinner {
  width: 28px;
  height: 28px;
  border: 3px solid #e4e7ed;
  border-top-color: #409EFF;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.whatif-loading-detail {
  font-size: 11px;
  color: #C0C4CC;
}

/* ── Error ── */
.whatif-error {
  padding: 16px;
  text-align: center;
  color: #F56C6C;
  font-size: 13px;
}

/* ── Result ── */
.whatif-result {
  padding: 16px;
}

.whatif-verdict {
  text-align: center;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
}

.whatif-verdict.fixed {
  background: #f0f9eb;
  color: #67C23A;
  border: 1px solid #e1f3d8;
}

.whatif-verdict.unfixed {
  background: #fef0f0;
  color: #F56C6C;
  border: 1px solid #fde2e2;
}

/* ── Three-way comparison ── */
.whatif-three-way {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
  margin-bottom: 12px;
}

.whatif-col {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  overflow: hidden;
}

.whatif-col-header {
  padding: 6px 10px;
  font-size: 11px;
  font-weight: 700;
  text-align: center;
}

.col-a { background: #f0f9eb; color: #67C23A; }
.col-b { background: #fef0f0; color: #F56C6C; }
.col-c { background: #ecf5ff; color: #409EFF; }

.whatif-col-body {
  padding: 8px 10px;
}

.whatif-col-body code {
  font-size: 11px;
  color: #303133;
  word-break: break-all;
  line-height: 1.5;
}

.whatif-col-meta {
  font-size: 10px;
  color: #909399;
  padding: 4px 10px 8px;
  text-align: center;
}

/* ── Fix description ── */
.whatif-fix-desc {
  padding: 10px 14px;
  background: #ecf5ff;
  border: 1px solid #d9ecff;
  border-radius: 6px;
  font-size: 13px;
  color: #303133;
  line-height: 1.6;
}

.whatif-fix-icon {
  margin-right: 4px;
}
</style>
