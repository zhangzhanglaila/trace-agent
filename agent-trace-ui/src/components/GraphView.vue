<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted, defineAsyncComponent } from 'vue'
import * as echarts from 'echarts'
import { useTraceStore } from '../store/traceStore'
import type { GraphNode, GraphEdge } from '../types/trace'

const TimelineView = defineAsyncComponent(() => import('./TimelineView.vue'))

const store = useTraceStore()
const chartRef = ref<HTMLDivElement | null>(null)
let chartInstance: echarts.ECharts | null = null

// ── Node colors ──
const NODE_COLORS: Record<string, string> = {
  llm: '#409EFF',
  tool: '#67C23A',
  branch: '#E6A23C',
  merge: '#909399',
  output: '#F56C6C',
  error: '#F56C6C',
}

const NODE_SYMBOLS: Record<string, string> = {
  llm: 'roundRect',
  tool: 'circle',
  branch: 'diamond',
  merge: 'triangle',
  output: 'pin',
  error: 'circle',
}

// ── Build ECharts option ──
const chartOption = computed(() => {
  const data = store.traceData
  if (!data) return {}

  const nodes = data.graph.nodes
  const edges = data.graph.edges
  const divergedNodeIds = new Set(
    nodes.filter(n => n.diverged).map(n => n.id)
  )

  // Compute layered layout positions
  const positions = computeLayout(nodes, edges)

  const chartNodes = nodes.map(node => {
    const pos = positions.get(node.id) || { x: 0, y: node.step_index * 80 }
    const isDiverged = node.diverged
    const isDivPoint = node.is_divergence_point
    const isRootCause = node.is_root_cause
    const isSelected = store.selectedNodeId === node.id
    const color = node.status === 'error' ? NODE_COLORS.error : NODE_COLORS[node.type] || '#909399'

    return {
      id: node.id,
      name: node.id,
      x: pos.x,
      y: pos.y,
      fixed: true,
      symbol: NODE_SYMBOLS[node.type] || 'circle',
      symbolSize: isDivPoint ? 36 : isRootCause ? 40 : isSelected ? 32 : 28,
      itemStyle: {
        color: color,
        borderColor: isRootCause ? '#F56C6C' : isDivPoint ? '#E6A23C' : isSelected ? '#303133' : '#fff',
        borderWidth: isRootCause ? 4 : isDivPoint ? 3 : isSelected ? 3 : 1,
        opacity: isDiverged ? 1.0 : 0.55,
        shadowBlur: isRootCause ? 16 : isDivPoint ? 8 : 0,
        shadowColor: isRootCause ? 'rgba(245, 108, 108, 0.6)' : 'rgba(230, 162, 60, 0.4)',
      },
      label: {
        show: true,
        formatter: node.label.length > 18 ? node.label.slice(0, 18) + '…' : node.label,
        fontSize: 11,
        position: 'right',
        color: isDiverged ? '#303133' : '#909399',
        fontWeight: isDivPoint ? 'bold' : 'normal',
      },
      tooltip: {
        formatter: () => buildTooltip(node),
      },
      data: node,
    }
  })

  const chartEdges = edges.map(edge => {
    const isDashed = edge.style === 'dashed'
    const targetDiverged = divergedNodeIds.has(edge.target)

    return {
      source: edge.source,
      target: edge.target,
      lineStyle: {
        color: targetDiverged ? '#F56C6C' : '#C0C4CC',
        type: isDashed ? 'dashed' : 'solid',
        width: isDashed ? 1.5 : 2,
        curveness: 0.2,
        opacity: targetDiverged ? 1.0 : 0.5,
      },
      label: {
        show: !!edge.label,
        formatter: edge.label,
        fontSize: 10,
        color: '#909399',
      },
    }
  })

  return {
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: '#fff',
      borderColor: '#e4e7ed',
      borderWidth: 1,
      textStyle: { color: '#303133', fontSize: 12 },
      extraCssText: 'max-width: 320px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); border-radius: 8px; padding: 8px;',
    },
    animation: true,
    animationDuration: 600,
    hoverable: true,
    series: [{
      type: 'graph',
      layout: 'none',
      data: chartNodes,
      edges: chartEdges,
      roam: true,
      draggable: false,
      emphasis: {
        focus: 'adjacency',
        itemStyle: { borderWidth: 3, borderColor: '#303133' },
        lineStyle: { width: 3 },
      },
      selectedMode: 'single',
      select: {
        itemStyle: { borderWidth: 3, borderColor: '#303133' },
      },
    }],
  }
})

// ── Layered DAG layout ──
function computeLayout(nodes: GraphNode[], _edges: GraphEdge[]): Map<string, { x: number, y: number }> {
  const positions = new Map<string, { x: number, y: number }>()
  const V_GAP = 70
  const H_GAP = 180
  const H_CENTER = 0

  // Group nodes by step_index (layer)
  const layers = new Map<number, GraphNode[]>()
  for (const node of nodes) {
    const layer = node.step_index
    if (!layers.has(layer)) layers.set(layer, [])
    layers.get(layer)!.push(node)
  }

  // Sort layers
  const sortedLayers = [...layers.keys()].sort((a, b) => a - b)

  for (const layerIdx of sortedLayers) {
    const layerNodes = layers.get(layerIdx)!
    const count = layerNodes.length
    const totalWidth = (count - 1) * H_GAP
    const startX = H_CENTER - totalWidth / 2

    layerNodes.forEach((node, i) => {
      positions.set(node.id, {
        x: startX + i * H_GAP,
        y: layerIdx * V_GAP + 60,
      })
    })
  }

  return positions
}

// ── Tooltip builder ──
function buildTooltip(node: GraphNode): string {
  const statusEmoji = node.status === 'error' ? '❌' : node.status === 'success' ? '✅' : '⏳'
  const typeColors: Record<string, string> = { llm: '#409EFF', tool: '#67C23A', branch: '#E6A23C', merge: '#909399', output: '#F56C6C', error: '#F56C6C' }
  const color = node.status === 'error' ? '#F56C6C' : (typeColors[node.type] || '#909399')

  let html = `<div style="font-family: monospace; font-size: 12px; line-height: 1.6;">`
  html += `<div style="font-weight: 700; margin-bottom: 4px;">
    <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${color};margin-right:6px;"></span>
    ${node.name}
  </div>`
  html += `<div>Status: ${statusEmoji} ${node.status}</div>`
  html += `<div>Type: <span style="color:${color};font-weight:600;">${node.type.toUpperCase()}</span></div>`

  if (node.error) {
    html += `<div style="color:#F56C6C;margin-top:4px;">Error: ${node.error}</div>`
  }

  if (node.latency_ms) {
    html += `<div>Latency: ${node.latency_ms.toFixed(1)}ms</div>`
  }

  if (node.is_root_cause) {
    html += `<div style="margin-top:4px;color:#F56C6C;font-weight:600;">🔴 ROOT CAUSE</div>`
  }

  if (node.is_divergence_point) {
    html += `<div style="margin-top:4px;color:#E6A23C;font-weight:600;">⚠ DIVERGENCE POINT</div>`
  }

  const inputKeys = Object.keys(node.inputs || {}).filter(k => k !== '_value')
  if (inputKeys.length > 0) {
    html += `<div style="margin-top:4px;color:#909399;">Inputs: ${inputKeys.join(', ')}</div>`
  }

  const outputKeys = Object.keys(node.outputs || {}).filter(k => k !== '_value')
  if (outputKeys.length > 0) {
    html += `<div style="margin-top:2px;color:#909399;">Outputs: ${outputKeys.join(', ')}</div>`
  }

  html += `</div>`
  return html
}

// ── Root cause focus state ──
const showRootCauseFlash = ref(false)
let initialAnimationDone = false

function focusRootCause() {
  if (!chartInstance || initialAnimationDone) return
  const rootNode = store.rootCauseNode
  if (!rootNode) return

  initialAnimationDone = true

  // Flash animation
  showRootCauseFlash.value = true
  setTimeout(() => { showRootCauseFlash.value = false }, 3000)

  // Auto-select root cause node
  setTimeout(() => {
    store.selectNode(rootNode.id)
    // Dispatch highlight action
    chartInstance?.dispatchAction({
      type: 'highlight',
      seriesIndex: 0,
      dataIndex: store.traceData?.graph.nodes.findIndex(n => n.id === rootNode.id),
    })
    // Show tooltip briefly
    chartInstance?.dispatchAction({
      type: 'showTip',
      seriesIndex: 0,
      dataIndex: store.traceData?.graph.nodes.findIndex(n => n.id === rootNode.id),
    })
  }, 400)

  // Hide tooltip after 2.5s
  setTimeout(() => {
    chartInstance?.dispatchAction({ type: 'hideTip' })
    chartInstance?.dispatchAction({ type: 'downplay', seriesIndex: 0 })
  }, 2500)
}

// ── Chart lifecycle ──
function initChart() {
  if (!chartRef.value) return
  chartInstance = echarts.init(chartRef.value, null, { renderer: 'canvas' })

  chartInstance.on('click', (params: any) => {
    if (params.dataType === 'node' && params.data?.data) {
      store.selectNode(params.data.data.id)
    } else {
      store.selectNode(null)
    }
  })

  updateChart()
}

function updateChart() {
  if (!chartInstance) return
  chartInstance.setOption(chartOption.value, true)

  // After render, auto-focus root cause
  if (!initialAnimationDone && store.rootCauseNode) {
    setTimeout(() => focusRootCause(), 600)
  }
}

function handleResize() {
  chartInstance?.resize()
}

watch(() => store.traceData, () => {
  initialAnimationDone = false
  showRootCauseFlash.value = false
  updateChart()
}, { deep: true })

watch(() => store.selectedNodeId, () => {
  updateChart()
})

onMounted(() => {
  initChart()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
})
</script>

<template>
  <div class="graph-view">
    <div class="graph-header">
      <h3>Execution Graph</h3>
      <div class="header-right">
        <div class="view-toggle">
          <button
            :class="{ active: store.viewMode === 'graph' }"
            @click="store.setViewMode('graph')"
          >Graph</button>
          <button
            :class="{ active: store.viewMode === 'timeline' }"
            @click="store.setViewMode('timeline')"
          >Timeline</button>
        </div>
        <div class="legend">
          <span class="legend-item"><span class="dot" style="background:#409EFF"></span>LLM</span>
          <span class="legend-item"><span class="dot" style="background:#67C23A"></span>Tool</span>
          <span class="legend-item"><span class="dot" style="background:#E6A23C"></span>Branch</span>
          <span class="legend-item"><span class="dot" style="background:#909399"></span>Merge</span>
          <span class="legend-item"><span class="dot" style="background:#F56C6C"></span>Error</span>
        </div>
      </div>
    </div>

    <!-- Graph View -->
    <div v-show="store.viewMode === 'graph'" ref="chartRef" class="chart-container"></div>

    <!-- Flash overlay for root cause -->
    <div v-if="showRootCauseFlash" class="root-cause-flash">
      <span class="flash-ring"></span>
      <span class="flash-label">🔴 Root Cause</span>
    </div>

    <!-- Timeline View -->
    <div v-show="store.viewMode === 'timeline'" class="timeline-container">
      <TimelineView />
    </div>
  </div>
</template>

<style scoped>
.graph-view {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  position: relative;
}

.graph-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
}

.graph-header h3 {
  margin: 0;
  font-size: 15px;
  color: #303133;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

/* ── View toggle ── */
.view-toggle {
  display: flex;
  background: #f0f2f5;
  border-radius: 6px;
  overflow: hidden;
}

.view-toggle button {
  padding: 4px 14px;
  border: none;
  background: transparent;
  font-size: 12px;
  cursor: pointer;
  color: #909399;
  font-weight: 500;
  transition: all 0.2s;
}

.view-toggle button.active {
  background: #409EFF;
  color: #fff;
}

.legend {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #909399;
}

.dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.chart-container {
  flex: 1;
  min-height: 420px;
  width: 100%;
}

.timeline-container {
  flex: 1;
  min-height: 420px;
  overflow-y: auto;
  padding: 12px;
}

/* ── Root cause flash overlay ── */
.root-cause-flash {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  pointer-events: none;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
}

.flash-ring {
  position: absolute;
  width: 80px;
  height: 80px;
  border: 3px solid #F56C6C;
  border-radius: 50%;
  animation: flash-pulse 1.2s ease-out 3;
  opacity: 0;
}

.flash-label {
  background: #F56C6C;
  color: #fff;
  padding: 8px 20px;
  border-radius: 20px;
  font-size: 14px;
  font-weight: 700;
  box-shadow: 0 4px 20px rgba(245, 108, 108, 0.5);
  animation: flash-fade 3s ease-out forwards;
}

@keyframes flash-pulse {
  0% { transform: scale(0.5); opacity: 1; }
  100% { transform: scale(3); opacity: 0; }
}

@keyframes flash-fade {
  0% { opacity: 0; transform: scale(0.8); }
  15% { opacity: 1; transform: scale(1); }
  80% { opacity: 1; }
  100% { opacity: 0; transform: scale(1.05); }
}

/* ── Responsive ── */
@media (max-width: 768px) {
  .header-right {
    flex-direction: column;
    gap: 8px;
  }
  .legend {
    gap: 8px;
  }
}
</style>
