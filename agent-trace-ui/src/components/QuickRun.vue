<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useTraceStore } from '../store/traceStore'

const store = useTraceStore()

interface AgentOption {
  entry: string
  path: string
  name: string
}

const agentOptions = ref<AgentOption[]>([])
const selectedAgent = ref('')
const customPath = ref('')
const showCustomInput = ref(false)
const inputA = ref('Plan a trip to Tokyo for hiking')
const inputB = ref('Plan a trip to Paris for hiking')
const running = ref(false)
const runError = ref<string | null>(null)

const effectiveAgentPath = computed(() => {
  if (showCustomInput.value) return customPath.value.trim()
  return selectedAgent.value
})

const agentLabel = computed(() => {
  if (showCustomInput.value) return 'Custom'
  if (!selectedAgent.value) return 'Demo'
  const opt = agentOptions.value.find(o => o.entry === selectedAgent.value)
  return opt ? `${opt.name} (${opt.path})` : selectedAgent.value
})

onMounted(async () => {
  try {
    const res = await fetch('/api/trace/agents')
    if (res.ok) {
      const data = await res.json()
      agentOptions.value = data.agents || []
    }
  } catch { /* non-critical */ }
})

async function runCompare() {
  running.value = true
  runError.value = null
  try {
    const body: Record<string, any> = {
      bug: store.bugEnabled,
      input_a: inputA.value,
      input_b: inputB.value,
    }
    if (effectiveAgentPath.value) {
      body.agent_path = effectiveAgentPath.value
    }
    const res = await fetch('/api/trace/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}))
      throw new Error(errData.error || `HTTP ${res.status}`)
    }
    const data = await res.json()
    store.loadTrace(data)
    store.whatIfData = data.what_if || null
    store.commitRun(effectiveAgentPath.value, inputA.value, inputB.value, store.bugEnabled)
  } catch (e: any) {
    runError.value = e.message || 'Run failed'
  } finally {
    running.value = false
  }
}

</script>

<template>
  <div class="quick-run">
    <div class="qr-header">
      <span class="qr-title">Quick Run</span>
      <span class="qr-subtitle">{{ agentLabel }}</span>
    </div>

    <div class="qr-body">
      <!-- Agent Selector -->
      <div class="qr-agent-select">
        <label class="qr-label">Agent</label>
        <select
          v-model="selectedAgent"
          class="qr-select"
          :disabled="running"
          @change="showCustomInput = false"
        >
          <option value="">Built-in Demo (TravelPlanner)</option>
          <option
            v-for="opt in agentOptions"
            :key="opt.entry"
            :value="opt.entry"
          >
            {{ opt.name }} ({{ opt.path }})
          </option>
          <option value="__custom__">Custom path...</option>
        </select>
        <input
          v-if="showCustomInput"
          v-model="customPath"
          type="text"
          class="qr-input qr-input-mono qr-custom-input"
          placeholder="my_agent.py:Agent"
          :disabled="running"
        />
      </div>

      <div class="qr-inputs">
        <div class="qr-field">
          <label class="qr-label">Input A (correct path)</label>
          <input
            v-model="inputA"
            type="text"
            class="qr-input"
            placeholder="e.g. Plan a trip to Tokyo for hiking"
            :disabled="running"
          />
        </div>
        <div class="qr-field">
          <label class="qr-label">Input B (test path)</label>
          <input
            v-model="inputB"
            type="text"
            class="qr-input"
            placeholder="e.g. Plan a trip to Paris for hiking"
            :disabled="running"
          />
        </div>
      </div>

      <button
        class="qr-run-btn"
        :class="{ running }"
        @click="runCompare"
        :disabled="running || !inputA || !inputB"
      >
        <span v-if="running" class="qr-spinner"></span>
        <span v-else>▶</span>
        {{ running ? 'Running...' : 'Run & Compare' }}
      </button>

      <div v-if="runError" class="qr-error">
        {{ runError }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.quick-run {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 12px;
}

.qr-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: linear-gradient(135deg, #fafbff, #f0f4ff);
  border-bottom: 1px solid #e4e7ed;
}

.qr-title {
  font-size: 14px;
  font-weight: 700;
  color: #303133;
}

.qr-subtitle {
  font-size: 12px;
  color: #909399;
}

.qr-body {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.qr-agent-select {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.qr-select {
  padding: 8px 12px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  font-size: 13px;
  color: #303133;
  outline: none;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.2s;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M3 4.5l3 3 3-3' fill='none' stroke='%23909399' stroke-width='1.5'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
  padding-right: 30px;
}

.qr-select:focus {
  border-color: #409EFF;
}

.qr-select:disabled {
  background: #f5f7fa;
  color: #C0C4CC;
}

.qr-custom-input {
  margin-top: 6px;
}

.qr-input-mono {
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', Consolas, monospace;
  font-size: 12px;
}

.qr-inputs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.qr-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.qr-label {
  font-size: 11px;
  font-weight: 600;
  color: #909399;
  text-transform: uppercase;
}

.qr-input {
  padding: 8px 12px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  font-size: 13px;
  color: #303133;
  outline: none;
  transition: border-color 0.2s;
}

.qr-input:focus {
  border-color: #409EFF;
}

.qr-input:disabled {
  background: #f5f7fa;
  color: #C0C4CC;
}

.qr-run-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 24px;
  background: linear-gradient(135deg, #409EFF, #337ecc);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.3);
  align-self: flex-start;
}

.qr-run-btn:hover:not(:disabled) {
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.4);
  transform: translateY(-1px);
}

.qr-run-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
}

.qr-run-btn.running {
  background: linear-gradient(135deg, #67C23A, #529b2e);
}

.qr-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.qr-error {
  color: #F56C6C;
  font-size: 12px;
  padding: 8px 12px;
  background: #fef0f0;
  border-radius: 6px;
}

@media (max-width: 600px) {
  .qr-inputs {
    grid-template-columns: 1fr;
  }
}
</style>
