<script setup lang="ts">
import { computed } from 'vue'
import { useTraceStore } from '../store/traceStore'

const store = useTraceStore()

const suggestion = computed(() => store.traceData?.fix_suggestion ?? '')
const diagnosis = computed(() => store.traceData?.diagnosis ?? null)

const lines = computed(() =>
  suggestion.value
    .split('\n')
    .map(l => l.trim())
    .filter(l => l.length > 0)
)
</script>

<template>
  <div class="fix-suggestion" v-if="suggestion">
    <div class="fix-header">
      <span class="fix-icon">💡</span>
      <span class="fix-title">Suggested Fix</span>
      <span v-if="diagnosis" class="fix-category">{{ diagnosis.category }}</span>
    </div>
    <ul class="fix-list">
      <li v-for="(line, i) in lines" :key="i">{{ line }}</li>
    </ul>
  </div>
</template>

<style scoped>
.fix-suggestion {
  background: linear-gradient(135deg, #ecf5ff 0%, #f0f9ff 100%);
  border: 1px solid #d9ecff;
  border-radius: 8px;
  padding: 16px;
  margin-top: 12px;
}

.fix-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.fix-icon {
  font-size: 18px;
}

.fix-title {
  font-size: 14px;
  font-weight: 700;
  color: #303133;
}

.fix-category {
  font-size: 11px;
  background: #409EFF;
  color: #fff;
  padding: 2px 8px;
  border-radius: 10px;
  margin-left: auto;
}

.fix-list {
  margin: 0;
  padding-left: 18px;
}

.fix-list li {
  font-size: 13px;
  color: #606266;
  line-height: 1.7;
  margin-bottom: 4px;
}

.fix-list li::marker {
  color: #409EFF;
}
</style>
