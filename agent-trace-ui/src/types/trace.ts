// ── Unified Trace Data Protocol ──

export interface Diagnosis {
  type: string
  confidence: string
  category: string
}

export interface RootCause {
  variable: string
  run_a: string
  run_b: string
  source: string
}

export interface GraphNode {
  id: string
  name: string
  type: 'llm' | 'tool' | 'branch' | 'merge' | 'output' | 'error'
  label: string
  status: 'success' | 'error' | 'pending'
  inputs: Record<string, any>
  outputs: Record<string, any>
  error?: string
  latency_ms?: number
  diverged: boolean
  step_index: number
  is_divergence_point?: boolean
  is_root_cause?: boolean
}

export interface GraphEdge {
  source: string
  target: string
  type: 'sequential' | 'branch_true' | 'branch_false'
  style: 'solid' | 'dashed'
  label?: string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  primary_run: string
  secondary_nodes: GraphNode[]
}

export interface FirstDivergence {
  type: string
  id: string
  description: string
  run_a: string | null
  run_b: string | null
}

export interface StepDiffItem {
  step_name: string
  only_in: string | null
  run_a_status: string | null
  run_b_status: string | null
  run_a_error: string | null
  run_b_error: string | null
  diverged: boolean
}

export interface BranchDiffItem {
  branch_id: string
  condition: string
  run_a_path: string
  run_b_path: string
  diverged: boolean
}

export interface PathImpactItem {
  index: number
  run_a: string | null
  run_b: string | null
  diverged: boolean
}

export interface DiffData {
  first_divergence: FirstDivergence | null
  step_diffs: StepDiffItem[]
  branch_diffs: BranchDiffItem[]
  path_impact: PathImpactItem[]
  has_diverged: boolean
  output_diverged: boolean
}

export interface OutputData {
  run_a: string
  run_b: string
  diverged: boolean
}

export interface MetaData {
  trace_id_a: string
  trace_id_b: string
  run_a_steps: number
  run_b_steps: number
}

export interface WhatIfRunC {
  trace_id: string
  steps: number
  output: string
}

export interface WhatIfData {
  run_c_output: string
  run_c_trace: WhatIfRunC
  run_b_output: string
  fix_description: string
  would_fix: boolean
}

export interface TraceData {
  verdict: string
  diagnosis: Diagnosis
  root_cause: RootCause
  graph: GraphData
  diff: DiffData
  output: OutputData
  fix_suggestion: string
  meta: MetaData
  explanation?: string
  what_if?: WhatIfData
}
