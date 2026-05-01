<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

interface LiveAgent {
  agent_id: string
  agent_name: string
  pid: number
  status: string
  timestamp: number
}

const agents = ref<LiveAgent[]>([])
let timer: ReturnType<typeof setInterval> | null = null

async function poll() {
  try {
    const res = await fetch('/api/trace/agents/active')
    if (res.ok) {
      const data = await res.json()
      agents.value = data.agents || []
    }
  } catch {
    agents.value = []
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
  <div v-if="agents.length > 0" class="live-indicator">
    <div v-for="agent in agents" :key="agent.agent_id" class="live-agent-row">
      <span class="live-dot"></span>
      <span class="live-text">
        <strong>{{ agent.agent_name }}</strong> is running
        <span class="live-pid">(PID {{ agent.pid }})</span>
      </span>
    </div>
    <span class="live-hint">{{ agents.length }} agent(s) connected</span>
  </div>
</template>

<style scoped>
.live-indicator {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 16px;
  background: linear-gradient(135deg, #f0f9eb, #e1f3d8);
  border: 1px solid #b3e19d;
  border-radius: 8px;
  margin-bottom: 12px;
  font-size: 13px;
}

.live-agent-row {
  display: flex;
  align-items: center;
  gap: 10px;
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
  font-size: 10px;
  color: #909399;
  margin-top: 2px;
}
</style>
