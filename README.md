<p align="center">
  <h1 align="center">AgentTrace</h1>
  <h3 align="center">Chrome DevTools for AI Agents</h3>
</p>

<p align="center">
  <b>We turn agent execution into a causal graph<br>and explain WHY two runs diverge.</b>
</p>

<p align="center">
  <a href="#30-second-experience"><b>30-Second Demo</b></a> ·
  <a href="#one-line"><b>One-Line Enable</b></a> ·
  <a href="#langchain"><b>LangChain Adapter</b></a> ·
  <a href="#how-it-works"><b>How It Works</b></a>
</p>

---

## 💡 The One Sentence

> **"Why did my agent fail on input B when it worked on input A?"**

AI agents are non-deterministic. The same agent, same prompt template, different input — one succeeds, one fails. Existing tools show you logs. AgentTrace shows you the **causal chain**:

```
Input → Execution Graph → Diff → Root Cause → Fix
```

---

## ⚡ 30-Second Experience

```bash
pip install agenttrace
```

```python
from agenttrace import enable
enable()
```

That's it. Open `http://127.0.0.1:8765`, click **Run Demo Agent**, and in under 30 seconds you'll see:

```
┌─────────────────────────────────────────────┐
│  !  Bug Detected                            │
│                                             │
│  Why this happened                          │
│  The agent diverged at "routing to          │
│  activity search": Run A took the 'true'    │
│  path but Run B took 'none'. This was       │
│  caused by `weather current result` —       │
│  Run A got "clear", Run B got "rain".       │
│                                             │
│  Root Cause                                 │
│  weather current result:                    │
│    Run A → "clear" · Run B → "rain"         │
│                                             │
│  Impact                                     │
│  Diverged at "routing" · Run B failed       │
│         ↓ View Full Analysis                │
└─────────────────────────────────────────────┘
```

No setup. No API keys. No code. You see a real bug, its root cause, and the fix — all on the first screen.

---

## 🔌 LangChain Adapter

```python
from agenttrace.adapters.langchain import enable
enable()
```

This patches `BaseChatModel.invoke()` on `langchain_core`, so **every** LangChain agent — including LangGraph, langchain_openai, langchain_anthropic — is automatically traced. Zero code changes to your agent.

| | AgentTrace | LangSmith |
|---|---|---|
| Trace & observe | ✅ | ✅ |
| Variable-level root cause | ✅ | ❌ |
| Causal graph diff | ✅ | ❌ |
| "Why did it diverge?" | ✅ | ❌ |
| Counterfactual engine | ✅ | ❌ |
| One-line enable | ✅ | ✅ |
| LangChain support | ✅ | ✅ |

---

## 🧠 How It Works

### Pipeline

```
Agent Run A ──→ Trace ──→ ExecutionGraph ──┐
                                            ├──→ Causal Diff ──→ Verdict + Fix
Agent Run B ──→ Trace ──→ ExecutionGraph ──┘
```

1. **Trace Capture** — Two runs are recorded with full step-level instrumentation (inputs, outputs, variable bindings, control flow)
2. **ExecutionGraph** — Each trace is compiled into a deterministic SSA-based IR with control flow graph and φ-nodes
3. **Causal Diff** — Graphs are aligned. Variable-level comparison identifies the exact divergence point and root cause
4. **Verdict + Fix** — Human-language explanation, diagnosis type, confidence score, and suggested fix

### Diff Types

| Type | What it detects | Example |
|---|---|---|
| `value_diverged` | Variable values differ between runs | `weather = "clear"` vs `"rain"` |
| `tool_missed` | Tool called in A but not B | `activity_search` vs `summarize` |
| `branch_diverged` | Control flow split differently | True path vs None path |
| `output_partial` | Run B produced incomplete output | Missing itinerary section |

---

## 🚀 Usage

### One-Line Enable (recommended)

```python
from agenttrace import enable, dev

# Option 1: Auto-attach — your agent appears as "Connected" in the UI
enable(auto_attach=True)

# Option 2: dev() — run twice, diff, open browser
dev(my_agent, "Tokyo", "Paris")
```

### CLI

```bash
# Diff two agent runs
python -m agent_obs.cli_main debug my_agent.py \
  -i "Plan a trip to Tokyo" \
  -j "Plan a trip to Paris"

# Run with tracing
python -m agent_obs.cli_main run my_agent.py -i "Tokyo"
```

### Explicit Instrumentation

```python
from agent_obs.instrument import trace_llm, trace_tool, auto_trace

@trace_llm("classify_intent")
def classify(query: str) -> str: ...

@trace_tool("weather")
def weather_api(city: str) -> str: ...

auto_trace()  # patches OpenAI + LangChain
```

---

## 🏗️ Architecture

```
                        AgentTrace
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  Agent Code ──→ TracedAgent ──→ TraceCapture             │
│                                      │                   │
│                                      ▼                   │
│                               ExecutionGraph             │
│                               (SSA + CFG + φ-nodes)      │
│                                      │                   │
│                     ┌────────────────┼──────────────┐    │
│                     ▼                ▼              ▼    │
│               SemanticResolver  AgentIR     SCM Engine   │
│               (Lattice-based)  (why/       (causal)     │
│                                 what_if)                │
│                     │                │              │    │
│                     └────────────────┼──────────────┘    │
│                                      ▼                   │
│                               TraceDiffResult            │
│                               (verdict + root cause      │
│                                + blast radius + fix)     │
│                                      │                   │
│                                      ▼                   │
│                          ┌──────────────────┐           │
│                          │  DevTools UI      │           │
│                          │  (Vue 3 + ECharts)│           │
│                          └──────────────────┘           │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Core Engine:**
- **ExecutionGraph** — Compiler-grade IR with SSA, CFG, φ-nodes, reaching definitions
- **AgentIR** — Semantic query layer: `why(node)`, `what_if(node, flip)`, `blame(variable)`
- **SCM Engine** — Structured causal models with intervention and counterfactual semantics
- **Trace Differ** — Graph-aligned diff with causal role matching and impact scoring

---

## 📂 Project Structure

```
AgentTrace/
├── agenttrace/                     # Public API shim
│   └── __init__.py                 # from agenttrace import enable, dev
├── agent_obs/                      # Core engine
│   ├── enable.py                   # enable() + dev()
│   ├── adapters/
│   │   └── langchain.py            # LangChain adapter
│   ├── execution_graph.py          # ExecutionGraph IR + SSA + CFG
│   ├── trace_core.py               # TracedAgent + TraceContext + SEM
│   ├── trace_diff.py               # TraceDiffer + causal verdict
│   ├── trace_export.py             # TraceExport (LangSmith-compatible)
│   ├── cli_main.py                 # CLI: run / diff / debug
│   ├── frontend_adapter.py         # Trace → unified JSON protocol
│   └── instrument/
│       └── auto.py                 # OpenAI + LangChain auto-patch
├── examples/
│   ├── travel_planner.py           # Demo: Travel Planner with real bug
│   ├── buggy_agent.py              # Configurable failure injection
│   ├── autonomous_agent.py         # Multi-tool reasoning agent
│   └── demo_cases.py               # 3 killer debug cases
├── agent-trace-ui/                 # Vue 3 DevTools frontend
│   ├── src/components/             # 13 UI components
│   ├── src/store/traceStore.ts     # Pinia state management
│   ├── src/types/trace.ts          # TypeScript protocol
│   └── server.py                   # API + static serving
├── pyproject.toml                  # pip install agenttrace
└── README.md
```

---

<p align="center">
  <b>Built for AI engineers who need to understand their agents,</b><br>
  <b>not just observe them.</b>
</p>

---

## License

MIT
