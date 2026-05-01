<script setup lang="ts">
import { useTraceStore } from '../store/traceStore'

const store = useTraceStore()
</script>

<template>
  <div class="bug-toggle-bar">
    <div class="bug-toggle-inner">
      <span class="bug-label">Bug Injection</span>
      <button
        class="bug-switch"
        :class="{ active: store.bugEnabled }"
        @click="store.toggleBug()"
        :disabled="store.loading"
      >
        <span class="bug-switch-knob"></span>
      </button>
      <span class="bug-state" :class="{ on: store.bugEnabled, off: !store.bugEnabled }">
        {{ store.bugEnabled ? 'ON — LLM misroutes at step 1' : 'OFF — Both runs correct' }}
      </span>
      <span v-if="store.loading" class="bug-loading">Loading...</span>
    </div>
  </div>
</template>

<style scoped>
.bug-toggle-bar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  margin-bottom: 8px;
}

.bug-toggle-inner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
}

.bug-label {
  font-size: 12px;
  font-weight: 700;
  color: #606266;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.bug-switch {
  width: 40px;
  height: 22px;
  border-radius: 11px;
  border: none;
  background: #C0C4CC;
  cursor: pointer;
  position: relative;
  transition: background 0.25s;
  padding: 0;
}

.bug-switch.active {
  background: #F56C6C;
}

.bug-switch:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.bug-switch-knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.25s;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
}

.bug-switch.active .bug-switch-knob {
  transform: translateX(18px);
}

.bug-state {
  font-size: 12px;
  font-weight: 500;
}

.bug-state.on {
  color: #F56C6C;
}

.bug-state.off {
  color: #67C23A;
}

.bug-loading {
  font-size: 11px;
  color: #909399;
}
</style>
