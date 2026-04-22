# AgentTrace — Reality Fork Engine

> Edit any AI decision. Watch the future split.

<!-- GIF placeholder: assets/demo.gif -->
<p align="center">
  <img src="assets/demo.gif" width="800"/>
</p>

---

## 🧠 What is this?

AgentTrace is an **AI decision timeline editor**.

It lets you:

- Visualize an AI agent's thinking process as an interactive graph
- Click ANY step in the reasoning chain
- Modify a decision (e.g. NORMAL → CRITICAL)
- Replay the agent and watch reality **fork into a new timeline**

---

## 💥 The Core Idea

Today, AI agents are:

> ❌ Black boxes  
> ❌ Non-editable  
> ❌ Single-path execution  

AgentTrace turns them into:

> ✅ Editable thought graphs  
> ✅ Replayable decision timelines  
> ✅ Branching multi-reality systems  

---

## 🔥 The Viral Moment

A simple edit changes everything:

```
Original Timeline:                    Forked Timeline:
Patient: mild discomfort              Patient: mild discomfort
   → CASE_NORMAL                         → CASE_CRITICAL
   → "Take rest"                         → "CALL EMERGENCY SERVICES"
```

**One click.  
Two realities.**

---

## 🚀 Quick Start

```bash
git clone https://github.com/yourname/AgentTrace
cd AgentTrace

pip install -r requirements.txt
python -m uvicorn server.demo_server:app --port 8765

# Open:
# http://localhost:8765
```

---

## 🧪 How it works

### 1. Run Agent

Click "Run Agent" → Watch step-by-step reasoning graph appear

### 2. Inspect Thought

Click any node → See AI internal state (thought, action, tool result)

### 3. Fork Reality

Edit a node:

```
CASE_NORMAL → CASE_CRITICAL
```

Then click:

**"MODIFY WORLD & RE-RUN"**

Watch the timeline **split in real-time** — original path dims to gray, forked path glows neon green.

---

## 🌌 Architecture

```
Agent Runtime:     step-based execution trace
Frontend:          D3.js interactive graph
Fork Engine:       snapshot → edit → replay → branch
Core trick:        deterministic replay + step-level mutation
```

---

## 🧠 Why this matters

We are moving from:

> "AI as a model"

to

> "AI as a controllable simulation system"

AgentTrace is a first step toward:

- ✅ editable agents
- ✅ branching cognition
- ✅ causal debugging of reasoning systems

---

## 🛠 Tech Stack

- **Backend**: FastAPI + WebSockets
- **Frontend**: D3.js + B站-style UI (glow effects, blur, gradients)
- **Agent**: MedicalTriageAgent with deterministic CASE flags
- **Fork Engine**: EventEmitter snapshots → ReplayEngine fork

---

## 📜 License

MIT