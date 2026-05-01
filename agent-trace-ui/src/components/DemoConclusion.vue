<script setup lang="ts">
import { computed } from 'vue'
import { useTraceStore } from '../store/traceStore'

const store = useTraceStore()

const hasBug = computed(() => {
  const d = store.traceData
  if (!d) return false
  return d.diff?.has_diverged || d.diff?.output_diverged ||
         d.output?.run_b?.includes('[FAIL]') ||
         d.output?.run_b?.includes('[PARTIAL]')
})

const rootCauseSummary = computed(() => {
  const rc = store.traceData?.root_cause
  if (!rc) return ''
  const varName = rc.variable || ''
  // Clean up the variable name for display
  const clean = varName.replace(/_/g, ' ').replace('result', '').trim()
  const aVal = (rc.run_a || '').length > 40 ? (rc.run_a || '').slice(0, 40) + '...' : (rc.run_a || '')
  const bVal = (rc.run_b || '').length > 40 ? (rc.run_b || '').slice(0, 40) + '...' : (rc.run_b || '')
  return `${clean}: Run A → "${aVal}", Run B → "${bVal}"`
})

const impactSummary = computed(() => {
  const d = store.traceData
  if (!d) return ''
  const parts: string[] = []
  if (d.diff?.first_divergence) {
    const fd = d.diff.first_divergence
    parts.push(`Diverged at "${fd.id}"`)
  }
  if (d.output?.run_b?.includes('[PARTIAL]')) {
    parts.push('Run B produced partial output')
  } else if (d.output?.run_b?.includes('[FAIL]')) {
    parts.push('Run B failed')
  }
  const nodesA = d.meta?.run_a_steps || 0
  const nodesB = d.meta?.run_b_steps || 0
  if (nodesA !== nodesB) {
    parts.push(`Run A: ${nodesA} steps, Run B: ${nodesB} steps`)
  }
  return parts.join(' · ')
})

const humanExplanation = computed(() => {
  return store.traceData?.explanation || ''
})
</script>

<template>
  <div v-if="store.demoRunComplete" class="conclusion" :class="{ bug: hasBug, ok: !hasBug }">
    <div class="conc-badge">
      <span v-if="hasBug" class="conc-icon">!</span>
      <span v-else class="conc-icon">&#10003;</span>
      <span class="conc-status">{{ hasBug ? 'Bug Detected' : 'All Clear' }}</span>
    </div>

    <div class="conc-body">
      <!-- Human-language explanation -->
      <div v-if="humanExplanation" class="conc-why">
        <span class="conc-why-label">Why this happened</span>
        <p class="conc-why-text">{{ humanExplanation }}</p>
      </div>

      <!-- Root cause + impact -->
      <div class="conc-details">
        <div class="conc-detail-row">
          <span class="conc-detail-label">Root Cause</span>
          <span class="conc-detail-value">{{ rootCauseSummary }}</span>
        </div>
        <div class="conc-detail-row">
          <span class="conc-detail-label">Impact</span>
          <span class="conc-detail-value">{{ impactSummary }}</span>
        </div>
      </div>
    </div>

    <div class="conc-action">
      <a href="#main-content" class="conc-scroll-link">View Full Analysis ↓</a>
    </div>
  </div>
</template>

<style scoped>
.conclusion {
  border-radius: 10px;
  padding: 20px 24px;
  margin-bottom: 16px;
  animation: slideDown 0.4s ease;
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-12px); }
  to { opacity: 1; transform: translateY(0); }
}

.conclusion.bug {
  background: linear-gradient(135deg, #fef0f0, #fde2e2);
  border: 1px solid #fbc4c4;
}

.conclusion.ok {
  background: linear-gradient(135deg, #f0f9eb, #e1f3d8);
  border: 1px solid #b3e19d;
}

.conc-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.conc-icon {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  font-weight: 800;
  color: #fff;
  flex-shrink: 0;
}

.bug .conc-icon {
  background: #F56C6C;
}

.ok .conc-icon {
  background: #67C23A;
}

.conc-status {
  font-size: 18px;
  font-weight: 800;
  letter-spacing: -0.3px;
}

.bug .conc-status {
  color: #C0392B;
}

.ok .conc-status {
  color: #389e0d;
}

.conc-body {
  margin-bottom: 12px;
}

.conc-why {
  margin-bottom: 12px;
}

.conc-why-label {
  font-size: 10px;
  font-weight: 700;
  color: #909399;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.conc-why-text {
  margin: 4px 0 0;
  font-size: 14px;
  color: #303133;
  line-height: 1.7;
  font-weight: 500;
}

.conc-details {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.conc-detail-row {
  display: flex;
  gap: 12px;
  font-size: 13px;
  align-items: baseline;
}

.conc-detail-label {
  font-weight: 600;
  color: #606266;
  min-width: 75px;
  flex-shrink: 0;
}

.conc-detail-value {
  color: #909399;
  word-break: break-all;
}

.bug .conc-detail-value {
  color: #C0392B;
}

.conc-action {
  text-align: center;
}

.conc-scroll-link {
  font-size: 12px;
  color: #409EFF;
  text-decoration: none;
  font-weight: 600;
}

.conc-scroll-link:hover {
  text-decoration: underline;
}
</style>
