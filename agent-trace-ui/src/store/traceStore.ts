import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { TraceData, GraphNode, WhatIfData } from '../types/trace'

export interface RunRecord {
  id: string
  runNumber: number
  agentPath: string
  inputA: string
  inputB: string
  bugEnabled: boolean
  timestamp: number
  traceData: TraceData
  label: string
}

export interface RunCompareResult {
  baseRun: RunRecord
  targetRun: RunRecord
  verdictChanged: boolean
  rootCauseChanged: boolean
  divergenceMoved: boolean
  outputChanged: boolean
  nodeCountDiff: number
  baseVerdict: string
  targetVerdict: string
  baseDiagnosis: string
  targetDiagnosis: string
  baseRootCause: string
  targetRootCause: string
  baseOutputB: string
  targetOutputB: string
  baseDivergence: string
  targetDivergence: string
}

let runCounter = 0

export const useTraceStore = defineStore('trace', () => {
  const traceData = ref<TraceData | null>(null)
  const selectedNodeId = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const viewMode = ref<'graph' | 'timeline'>('graph')
  const bugEnabled = ref(true)
  const whatIfData = ref<WhatIfData | null>(null)
  const whatIfLoading = ref(false)
  const whatIfError = ref<string | null>(null)
  const runs = ref<RunRecord[]>([])
  const activeRunId = ref<string | null>(null)
  const compareMode = ref(false)
  const compareBaseRunId = ref<string | null>(null)

  // ── Computed ──
  const selectedNode = computed<GraphNode | null>(() => {
    if (!traceData.value || !selectedNodeId.value) return null
    return traceData.value.graph.nodes.find(n => n.id === selectedNodeId.value) || null
  })

  const divergedNodes = computed(() => {
    if (!traceData.value) return []
    return traceData.value.graph.nodes.filter(n => n.diverged)
  })

  const divergencePoint = computed(() => {
    if (!traceData.value) return null
    return traceData.value.graph.nodes.find(n => n.is_divergence_point) || null
  })

  const rootCauseNode = computed(() => {
    if (!traceData.value) return null
    return traceData.value.graph.nodes.find(n => n.is_root_cause) || null
  })

  const hasError = computed(() => {
    if (!traceData.value) return false
    return traceData.value.output.run_b.includes('[FAIL]') ||
           traceData.value.output.run_b.includes('[PARTIAL]')
  })

  const explanationText = computed(() => {
    if (!traceData.value) return ''
    if (traceData.value.explanation) return traceData.value.explanation
    const d = traceData.value
    const rc = d.root_cause
    if (!rc || !rc.variable) return d.verdict
    const divergence = d.diff.first_divergence
    let text = `Run B failed because at the decision step, the agent selected \`${rc.run_b}\` instead of \`${rc.run_a}\`. `
    if (divergence) {
      text += `This divergence at "${divergence.id}" caused downstream errors. `
    }
    text += `The root cause is the \`${rc.variable}\` variable: Run A correctly used \`${rc.run_a}\`, but Run B incorrectly used \`${rc.run_b}\`. `
    if (d.fix_suggestion) {
      const firstLine = d.fix_suggestion.split('\n')[0].replace(/^[-\s]+/, '')
      text += `Recommendation: ${firstLine}.`
    }
    return text
  })

  const activeRun = computed(() => {
    if (!activeRunId.value) return null
    return runs.value.find(r => r.id === activeRunId.value) || null
  })

  const compareBaseRun = computed(() => {
    if (!compareBaseRunId.value) return null
    return runs.value.find(r => r.id === compareBaseRunId.value) || null
  })

  const compareResult = computed<RunCompareResult | null>(() => {
    if (!compareBaseRun.value || !activeRun.value) return null
    if (compareBaseRun.value.id === activeRun.value.id) return null
    const base = compareBaseRun.value.traceData
    const target = activeRun.value.traceData
    const brc = base.root_cause
    const trc = target.root_cause
    const bdiv = base.diff?.first_divergence
    const tdiv = target.diff?.first_divergence
    return {
      baseRun: compareBaseRun.value,
      targetRun: activeRun.value,
      verdictChanged: base.verdict !== target.verdict,
      rootCauseChanged: (brc?.variable || '') !== (trc?.variable || '') ||
                        (brc?.run_b || '') !== (trc?.run_b || ''),
      divergenceMoved: (bdiv?.id || '') !== (tdiv?.id || ''),
      outputChanged: base.output?.run_b !== target.output?.run_b,
      nodeCountDiff: target.graph?.nodes?.length - base.graph?.nodes?.length,
      baseVerdict: base.verdict?.slice(0, 80) || '',
      targetVerdict: target.verdict?.slice(0, 80) || '',
      baseDiagnosis: `${base.diagnosis?.type || '?'} / ${base.diagnosis?.confidence || '?'}`,
      targetDiagnosis: `${target.diagnosis?.type || '?'} / ${target.diagnosis?.confidence || '?'}`,
      baseRootCause: brc ? `${brc.variable} → ${brc.run_b}` : 'none',
      targetRootCause: trc ? `${trc.variable} → ${trc.run_b}` : 'none',
      baseOutputB: base.output?.run_b?.slice(0, 60) || '',
      targetOutputB: target.output?.run_b?.slice(0, 60) || '',
      baseDivergence: bdiv ? `${bdiv.id} (${bdiv.type})` : 'none',
      targetDivergence: tdiv ? `${tdiv.id} (${tdiv.type})` : 'none',
    }
  })

  // ── Actions ──
  function loadTrace(data: TraceData) {
    traceData.value = data
    selectedNodeId.value = null
    whatIfData.value = null
    whatIfError.value = null
  }

  function commitRun(agentPath: string, inputA: string, inputB: string, bug: boolean) {
    if (!traceData.value) return
    runCounter++
    const id = Date.now().toString(36) + runCounter
    const shortAgent = agentPath
      ? agentPath.split('/').pop()?.replace('.py', '') || agentPath
      : 'Demo'
    const label = `${shortAgent}: ${inputA.slice(0, 30)}`
    const record: RunRecord = {
      id,
      runNumber: runCounter,
      agentPath,
      inputA,
      inputB,
      bugEnabled: bug,
      timestamp: Date.now(),
      traceData: JSON.parse(JSON.stringify(traceData.value)),
      label,
    }
    // Remove duplicates
    runs.value = [
      record,
      ...runs.value.filter(
        r => !(r.agentPath === agentPath && r.inputA === inputA && r.inputB === inputB)
      ),
    ].slice(0, 50)
    activeRunId.value = id
  }

  function loadRun(id: string) {
    const run = runs.value.find(r => r.id === id)
    if (run) {
      traceData.value = JSON.parse(JSON.stringify(run.traceData))
      activeRunId.value = id
      selectedNodeId.value = null
      whatIfData.value = null
      whatIfError.value = null
    }
  }

  function startCompare() {
    compareMode.value = true
    compareBaseRunId.value = activeRunId.value
  }

  function setCompareBase(id: string) {
    compareBaseRunId.value = id
  }

  function cancelCompare() {
    compareMode.value = false
    compareBaseRunId.value = null
  }

  const demoRunComplete = ref(false)
  const showingFix = ref(false)

  async function fetchDemo(bug: boolean = true) {
    loading.value = true
    error.value = null
    try {
      let res = await fetch('/api/trace/dev')
      if (!res.ok) {
        const bugParam = bug ? 'on' : 'off'
        res = await fetch(`/api/trace/demo?bug=${bugParam}`)
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      traceData.value = data
      whatIfData.value = (data.what_if ?? null) as WhatIfData | null
    } catch (e: any) {
      error.value = e.message || 'Failed to load trace'
      await fetchDemoFallback()
    } finally {
      loading.value = false
    }
  }

  async function runDemo() {
    demoRunComplete.value = false
    showingFix.value = false
    loading.value = true
    error.value = null
    try {
      // Step 1: Run demo with bug ON (buggy version)
      const resBug = await fetch('/api/trace/demo?bug=on')
      if (!resBug.ok) throw new Error(`HTTP ${resBug.status}`)
      const bugData = await resBug.json()
      traceData.value = bugData
      whatIfData.value = (bugData.what_if ?? null) as WhatIfData | null
      commitRun('', 'Plan a trip to Tokyo (correct)', 'Plan a trip to Paris (buggy)', true)

      // Step 2: Run demo with bug OFF (correct version)
      const resOk = await fetch('/api/trace/demo?bug=off')
      if (!resOk.ok) throw new Error(`HTTP ${resOk.status}`)
      const okData = await resOk.json()
      traceData.value = okData
      commitRun('', 'Plan a trip to Tokyo (correct)', 'Plan a trip to Paris (correct)', false)

      // Step 3: Auto-enter compare mode — buggy vs correct
      const bugRun = runs.value[1]  // Second most recent (bug ON)
      const okRun = runs.value[0]   // Most recent (bug OFF)
      if (bugRun && okRun) {
        loadRun(okRun.id)           // Show correct version
        compareMode.value = true
        compareBaseRunId.value = bugRun.id  // Compare against buggy
      }

      demoRunComplete.value = true
    } catch (e: any) {
      error.value = e.message || 'Failed to run demo'
      await fetchDemoFallback()
    } finally {
      loading.value = false
    }
  }

  function showFix() {
    showingFix.value = true
  }

  async function fetchDemoFallback() {
    try {
      const mod = await import('../api/demo-data')
      traceData.value = mod.demoData as TraceData
      error.value = null
    } catch (e: any) {
      error.value = 'Failed to load demo data'
    }
  }

  async function uploadTrace(file: File) {
    loading.value = true
    error.value = null
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      traceData.value = data as TraceData
      whatIfData.value = (data.what_if ?? null) as WhatIfData | null
    } catch (e: any) {
      error.value = `Failed to parse trace file: ${e.message}`
    } finally {
      loading.value = false
    }
  }

  async function fetchWhatIf() {
    whatIfLoading.value = true
    whatIfError.value = null
    try {
      const res = await fetch('/api/trace/what-if', { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      whatIfData.value = (data.what_if ?? data) as WhatIfData
      if (traceData.value) {
        traceData.value.what_if = whatIfData.value ?? undefined
      }
    } catch (e: any) {
      whatIfError.value = e.message || 'Failed to run what-if analysis'
    } finally {
      whatIfLoading.value = false
    }
  }

  function toggleBug() {
    bugEnabled.value = !bugEnabled.value
    fetchDemo(bugEnabled.value)
  }

  function selectNode(nodeId: string | null) {
    selectedNodeId.value = nodeId
  }

  function setViewMode(mode: 'graph' | 'timeline') {
    viewMode.value = mode
  }

  return {
    traceData,
    selectedNodeId,
    selectedNode,
    loading,
    error,
    viewMode,
    bugEnabled,
    whatIfData,
    whatIfLoading,
    whatIfError,
    runs,
    activeRunId,
    activeRun,
    compareMode,
    compareBaseRunId,
    compareBaseRun,
    compareResult,
    startCompare,
    setCompareBase,
    cancelCompare,
    divergedNodes,
    divergencePoint,
    rootCauseNode,
    hasError,
    explanationText,
    demoRunComplete,
    showingFix,
    loadTrace,
    commitRun,
    loadRun,
    fetchDemo,
    runDemo,
    showFix,
    uploadTrace,
    fetchWhatIf,
    toggleBug,
    selectNode,
    setViewMode,
  }
})
