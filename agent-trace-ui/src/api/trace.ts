import type { TraceData } from '../types/trace'

const BASE = '/api/trace'

export async function fetchDemoTrace(): Promise<TraceData> {
  const res = await fetch(`${BASE}/demo`)
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json()
}

export async function fetchTraceFromFile(file: File): Promise<TraceData> {
  const text = await file.text()
  return JSON.parse(text) as TraceData
}
