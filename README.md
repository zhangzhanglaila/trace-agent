<p align="center">
  <h1 align="center">🧠 AgentTrace</h1>
  <h3 align="center">Chrome DevTools for AI Agents</h3>
</p>

<p align="center">
  Answer one question: <b>"Why did my agent behave differently?"</b>
</p>

---

## ❓ Problem

AI agents are **non-deterministic**. The same input can produce different outputs.
The same query to Tokyo might work perfectly, while Paris fails with an error cascade.

**Current debugging tools show WHAT happened.** AgentTrace shows **WHY.**

## 💡 Solution

AgentTrace is an **Agent Debugging DevTool** that pinpoints the exact moment a decision
went wrong, identifies which variable caused the divergence, and traces how the error
propagated through the entire execution.

```
VERDICT
Run B failed because the LLM router selected `summarize` instead of
`activity_search` — the wrong tool received incompatible arguments,
triggering an error cascade.

ROOT CAUSE
Variable:  selected_tool (LLM output)
  Run A:   activity_search
  Run B:   summarize

DIAGNOSIS
Type:       LLM Hallucination → Error Cascade
Confidence: High
```

## ⚡ 30-Second Demo

```bash
# 1. Generate a trace with a real bug
python examples/travel_planner.py

# 2. Start the DevTools UI
cd agent-trace-ui
npm install && npm run dev

# 3. Open http://localhost:5173
```

You'll see the **Execution Graph** with:
- ❌ **Red path**: the diverged (failing) execution
- 🔴 **Pulsing marker**: the exact root cause node
- 💡 **Suggested fix**: how to prevent this bug

## 🖼️ DevTools UI

```
┌──────────────────────────────────────────────┐
│ 🧠 VERDICT + DIAGNOSIS                        │
│ ❌ Run B failed: LLM selected `summarize`     │
│    instead of `activity_search`               │
├──────────────────────────────────────────────┤
│ 🌳 EXECUTION GRAPH (DAG)                     │
│                                                │
│   LLM ──→ Tool ──→ LLM ──→ Branch ──→ ...    │
│                              │                 │
│                    ┌─────────┴─────────┐       │
│                    │ T (correct)  F (bug!)│    │
│                    ↓                   ↓      │
│               activity_search     summarize   │
│                    │              🔴 ROOT     │
│                    ↓              CAUSE       │
│               [OK plan]       [FAIL cascade]  │
├──────────────┬────────────────────────────────┤
│ 🔍 DIFF      │ 📦 STEP DETAIL                 │
│              │                                 │
│ Activity:    │ Input: {activity: "hiking"}     │
│   A: search  │ Output: "Ideal conditions"      │
│   B: summary │ Status: ✅ success              │
└──────────────┴────────────────────────────────┘
```

## 🧠 How It Works

### 1. Trace → ExecutionGraph → Diff

```
Agent Run A ──→ Trace ──→ ExecutionGraph ──┐
                                             ├──→ Causal Diff → Verdict
Agent Run B ──→ Trace ──→ ExecutionGraph ──┘
```

### 2. Causal Analysis Engine

- **Variable-level diff**: Compares `produces`/`consumes` between aligned steps
- **Impact scoring**: Ranks divergence points by blast radius
- **Error classification**: LLM Hallucination, Retry Loop, Input Sensitivity, etc.
- **Counterfactual engine**: "What if `selected_tool` had been `activity_search`?"

### 3. DevTools UI (Vue 3 + ECharts)

- **Graph View**: Interactive DAG with node types (LLM/Tool/Branch/Merge/Error)
- **Diff Panel**: Step-by-step comparison with divergence markers
- **Step Detail**: Click any node to inspect inputs/outputs/status
- **Timeline Mode**: Linear execution chronology
- **Comparison Mode**: Left-right Run A vs Run B
- **Drag & Drop**: Upload `trace.json` → instant analysis

## 🏗️ Architecture

```
                       AgentTrace OS
┌─────────────────────────────────────────────────────┐
│                                                     │
│  Agent Code ──→ TracedAgent ──→ TraceCapture        │
│                                     │               │
│                                     ▼               │
│                              ExecutionGraph          │
│                              (SSA + CFG + φ)         │
│                                     │               │
│                    ┌────────────────┼────────────┐   │
│                    ▼                ▼            ▼   │
│              SemanticResolver  AgentIR   SCM Engine │
│              (Lattice-based)   (why/     (causal)   │
│                                what_if)             │
│                    │                │            │   │
│                    └────────────────┼────────────┘   │
│                                     ▼               │
│                              TraceDiffResult         │
│                              (verdict + root cause   │
│                               + blast radius +       │
│                                suggested fix)        │
│                                     │               │
│                                     ▼               │
│                         ┌──────────────────┐        │
│                         │  DevTools UI      │        │
│                         │  (Vue 3 + ECharts)│        │
│                         └──────────────────┘        │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Core Components:**
- **ExecutionGraph**: Compiler-grade IR with SSA, CFG, φ-nodes, and reaching definitions
- **AgentIR**: Semantic query layer — `why(node)`, `what_if(node, flip)`, `blame(variable)`
- **SCM Engine**: Structured causal models with intervention and counterfactual semantics
- **Trace Compiler**: Deterministic 3-phase trace → ExecutionGraph compiler
- **Trace Differ**: Graph-aligned diff with causal role matching and impact scoring

## 🚀 Quick Start

### CLI

```bash
# Diff two agent runs interactively
python -m agent_obs.cli_main debug examples/travel_planner.py \
  -i "Plan a trip to Tokyo for hiking" \
  -j "Plan a trip to Paris for hiking"

# Run a single agent with tracing
python -m agent_obs.cli_main run examples/travel_planner.py \
  -i "Plan a trip to Tokyo for hiking"
```

### Web UI

```bash
# Terminal 1: Backend
cd agent-trace-ui
pip install -r ../requirements.txt  # if needed
python server.py --port 8765

# Terminal 2: Frontend
cd agent-trace-ui
npm install && npm run dev
# Open http://localhost:5173
```

### Python API

```python
from examples.travel_planner import TravelPlanner
from agent_obs.trace_core import TracedAgent, explain_diff
from agent_obs.trace_export import TraceExport
from agent_obs.trace_diff import TraceDiffer, render_causal_verdict

# Run two traces
agent_a = TravelPlanner(enable_bug=False)
traced_a = TracedAgent(agent_a)
traced_a.run("Plan a trip to Tokyo for hiking")

agent_b = TravelPlanner(enable_bug=True)
traced_b = TracedAgent(agent_b)
traced_b.run("Plan a trip to Paris for hiking")

# Diff and explain
export_a = TraceExport.from_file(traced_a.last_trace_path)
export_b = TraceExport.from_file(traced_b.last_trace_path)
differ = TraceDiffer(export_a, export_b)
diff_result = differ.diff()
diff_result.causal_narrative = explain_diff(traced_a.last_ctx, traced_b.last_ctx)

print(render_causal_verdict(diff_result))
```

## 📂 Project Structure

```
AgentTrace/
├── agent_obs/                       # Core engine
│   ├── execution_graph.py           # ExecutionGraph IR + SSA + CFG
│   ├── trace_core.py               # TracedAgent + TraceContext + SEM
│   ├── trace_diff.py               # TraceDiffer + causal verdict
│   ├── trace_export.py             # TraceExport (LangSmith-compatible)
│   ├── cli_main.py                 # CLI: run / diff / debug
│   └── frontend_adapter.py         # Trace → unified JSON protocol
├── examples/
│   ├── travel_planner.py           # 🌟 Demo: Travel Planner with real bug
│   ├── buggy_agent.py              # Configurable failure injection
│   ├── autonomous_agent.py         # Multi-tool reasoning agent
│   └── demo_cases.py               # 3 killer debug cases
├── agent-trace-ui/                 # Vue 3 DevTools frontend
│   ├── src/
│   │   ├── components/
│   │   │   ├── VerdictCard.vue     # One-line verdict + diagnosis
│   │   │   ├── GraphView.vue       # ECharts DAG visualization
│   │   │   ├── DiffPanel.vue       # Side-by-side diff analysis
│   │   │   ├── StepDetail.vue      # Click-to-inspect node detail
│   │   │   └── FixSuggestion.vue   # Actionable fix card
│   │   ├── views/DebugView.vue     # Main 4-panel layout
│   │   ├── store/traceStore.ts     # Pinia state management
│   │   └── types/trace.ts          # TypeScript protocol
│   └── server.py                   # Demo API server
├── test_v2_compiler.py             # Compiler correctness tests
└── test_explain_engine.py          # Causal engine tests
```

## 🎯 Why This Matters

We are moving from:

> "AI agent debugging = reading log files"

to

> "AI agent debugging = Chrome DevTools for decision-making"

AgentTrace gives you:
- **Causal debugging**: Not just "what happened" but "why it happened"
- **Variable-level root cause**: Pinpoint the exact variable that diverged
- **Counterfactual reasoning**: "What if the LLM had picked the right tool?"
- **Visual blast radius**: See how one bad decision cascades through the system
- **Suggested fixes**: Actionable guardrails based on error classification

---

<p align="center">
  <b>Built for AI engineers who need to understand their agents,</b><br>
  <b>not just observe them.</b>
</p>

---

## License

MIT
