# AgentTrace — Causal Semantic IR Engine

> "I changed one AI decision... and its future completely diverged"

---

## The Fork in Action

```
ORIGINAL TIMELINE                    FORKED TIMELINE (CASE_NORMAL → CASE_CRITICAL)

n1: MOV R_query="Patient..."         n1: MOV R_query="Patient..."
n2: CALL diagnose → R_result         n2: CALL diagnose → R_result
n3: EQ @R_result=CASE_NORMAL         n3: EQ @R_result=CASE_CRITICAL  ← MODIFIED
   ↓ (R_flag=False)                     ↓ (R_flag=True)
n5a: R_out="REST AND FLUIDS"         n5b: R_out="CALL 911"  ← DIVERGENCE!
n6: HALT                             n6: HALT
```

**Result:**
- Original: "Rest and fluids"
- Forked: "CALL 911"

### Visual Timeline

```
                    ┌─────────────────┐
                    │  n1: MOV query  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  n2: CALL diag  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  n3: EQ flag    │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │ (R_flag=False)    (R_flag=True) │
              ↓                           ↓
     ┌────────┴────────┐         ┌────────┴────────┐
     │ n5a: REST AND   │         │ n5b: CALL 911   │  ← DIVERGENCE
     │    FLUIDS       │         │    EMERGENCY    │
     └────────┬────────┘         └────────┬────────┘
              │                           │
              └───────────┬───────────────┘
                          ↓
                    ┌────────┴────────┐
                    │    n6: HALT     │
                    └─────────────────┘
```

---

<p align="center">
  <img src="assets/demo.gif" width="800"/>
</p>

---

## Causal Analysis (v1.1)

AgentTrace provides true counterfactual causal analysis:

```bash
python agenttrace.py causal examples/case_mild_discomfort.json
```

Output:
```
============================================================
CAUSAL SEMANTIC ANALYSIS
============================================================

Query: Patient has mild discomfort

[RESULT] REST AND FLUIDS

--- CAUSAL PARENTS ---
  R_flag = True
    If flipped: REST AND FLUIDS → EMERGENCY PROTOCOL: CALL 911
    [CRITICAL]

--- COUNTERFACTUAL EXPLANATION ---
Result: REST AND FLUIDS
Causes:
  - R_flag = True [CRITICAL]
    If R_flag=False → EMERGENCY PROTOCOL: CALL 911

--- CRITICAL PATH ---
  n1 → n3 → n6

Minimal causal chain (pruned):
  n1: MOV ['R_query', 'Patient has mild discomfort']
  n3: EQ ['@R_result', 'CASE_CRITICAL', 'R_flag']
  n6: HALT []
```

**Key differences from v1.0:**
- **Causal parents**: Uses fork-and-check to determine which variables are critical
- **Counterfactual**: Shows what would happen if a variable had a different value
- **Critical path**: Prunes non-essential nodes from the causal chain

---

## What is this?

AgentTrace is a **Causal Semantic IR Engine** for AI agents. It provides:

- **Causal Explainability**: Understand why an AI made each decision
- **Reality Forking**: Edit any decision point, replay the future
- **Semantic Analysis**: Track value flow through the execution DAG

### The Viral Moment

```
Original Timeline:                    Forked Timeline:
Patient: mild discomfort              Patient: mild discomfort
   → CASE_NORMAL                         → CASE_CRITICAL
   → "Rest and fluids"                    → "CALL 911"
```

**One edit. Two realities.**

---

## Quick Start

```bash
# CLI usage
python agenttrace.py explain examples/case_mild_discomfort.json
python agenttrace.py fork examples/case_mild_discomfort.json

# Web demo
python -m uvicorn server.demo_server:app --port 8765
# Open http://localhost:8765
```

---

## Architecture

```
User Query → ExecutionGraph → DAG → SemanticResolver → Causal Explanation
                              ↓
                         Fork Engine
                              ↓
                      Alternative Timeline
```

**Core Components:**
- **ExecutionGraph**: Program representation (IR + SSA + CFG)
- **SemanticResolver**: Lattice-based value resolution
- **DAGCache**: Canonical node interning for deduplication
- **Fork Engine**: Snapshot → Modify → Replay → Branch

---

## CLI Usage

### Explain a Case

```bash
python agenttrace.py explain examples/case_mild_discomfort.json
```

Output:
```
============================================================
AGENTTRACE CAUSAL EXPLANATION
============================================================

Query: Patient has mild discomfort

Expected: NORMAL

--- EXECUTION RESULT ---
R_result = CALL(diagnose)
R_flag   = False
R_out    = REST AND FLUIDS

--- SEMANTIC ANALYSIS ---
R_out @ n6: phi = φ(n5a:REST AND FLUIDS, n5b:EMERGENCY PROTOCOL: CALL 911)
  Definition site: n5a
  Reasoning: ["Reaching definitions: ['n5a', 'n5b']", ...]

--- CAUSAL NARRATIVE ---
Path: n1 → n2 → n3 → n4 → n5b → n6
  Because: n1 → n4: BRANCH on R_flag → ['n5b', 'n5a']
```

### Fork and Replay

```bash
python agenttrace.py fork examples/case_mild_discomfort.json
```

Output:
```
[ORIGINAL] R_out = REST AND FLUIDS
[FORKED]  R_out = EMERGENCY PROTOCOL: CALL 911

============================================================
FORK DIVERGENCE:
  Original: REST AND FLUIDS
  Forked:   EMERGENCY PROTOCOL: CALL 911
============================================================
VERIFIED: Fork correctly changed outcome from REST to EMERGENCY
```

---

## Example Case Format

```json
{
  "query": "Patient has mild discomfort",
  "expected": {
    "severity": "NORMAL",
    "recommendation": "Rest and fluids"
  },
  "fork_at": "n3",
  "patch": {
    "op": "MOV",
    "args": ["R_flag", "True"]
  },
  "expected_forked": {
    "severity": "CRITICAL",
    "recommendation": "CALL 911"
  }
}
```

---

## Key Concepts

### Semantic Lattice

```
Unknown
   ↓
Symbolic(@x)    ← register reference
   ↓
Constant(v)     ← concrete value
   ↓
Phi([incoming]) ← join point (implicit in SSA)
   ↓
Computed(op, args) ← operation result
```

### Causal Narrative

Instead of just tracing execution, AgentTrace generates **Because/Therefore** narratives:

```
Because: n3 → EQ(@R_result, CASE_CRITICAL, R_flag)
Therefore: n4 → BRANCH(R_flag, [n5b, n5a])
```

---

## Why This Matters

We are moving from:

> "AI as a black box"

to

> "AI as an editable simulation system"

AgentTrace enables:
- Causal debugging of AI reasoning
- Editable decision timelines
- Branching multi-reality systems

---

## Tech Stack

- **ExecutionGraph**: Python IR with SSA + CFG
- **SemanticResolver**: Lattice-based semantic analysis
- **Server**: FastAPI + WebSockets
- **Frontend**: D3.js interactive graph

---

## Files

```
agent_obs/
├── execution_graph.py   # Core ExecutionGraph + SemanticResolver
├── observe.py            # ReAct instrumentation
├── emitter.py            # Event emitter with pause support
└── replay.py            # Fork and replay engine

server/
└── demo_server.py       # FastAPI + WebSocket server

examples/
└── case_mild_discomfort.json  # Example case file

agenttrace.py            # CLI entry point
demo.html                # Web demo frontend
```

---

## License

MIT