<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

interface AgentStatus {
  status: string
  agent_name: string
  pid: number
  alive: boolean
  error?: string
}

const status = ref<AgentStatus | null>(null)
let timer: ReturnType<typeof setInterval> | null = null

async function poll() {
  try {
    const res = await fetch('/api/trace/agents/active')
    if (res.ok) {
      const data = await res.json()
      if (data.status && data.status !== 'none') {
        status.value = data as AgentStatus
      } else {
        status.value = null
      }
    }
  } catch {
    status.value = null
  }
}

onMounted(() => {
  poll()
  timer = setInterval(poll, 3000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div v-if="status && status.alive" class="live-indicator">
    <span class="live-dot"></span>
    <span class="live-text">
      <strong>{{ status.agent_name }}</strong> is running
      <span class="live-pid">(PID {{ status.pid }})</span>
    </span>
    <span class="live-hint">Open Quick Run to trace this agent</span>
  </div>
</template>

<style scoped>
.live-indicator {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  background: linear-gradient(135deg, #f0f9eb, #e1f3d8);
  border: 1px solid #b3e19d;
  border-radius: 8px;
  margin-bottom: 12px;
  font-size: 13px;
}

.live-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #67C23A;
  box-shadow: 0 0 6px rgba(103, 194, 58, 0.5);
  animation: pulse 2s infinite;
  flex-shrink: 0;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.live-text {
  color: #303133;
}

.live-text strong {
  color: #529b2e;
}

.live-pid {
  font-size: 11px;
  color: #909399;
  font-family: monospace;
}

.live-hint {
  font-size: 11px;
  color: #909399;
  margin-left: auto;
}
</style>
