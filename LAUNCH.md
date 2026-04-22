# AgentTrace — GIF Storyboard & Launch Copy

## 📹 10-Second GIF Storyboard (逐帧)

**目标**: 1秒看懂，3秒上头，5秒想 clone

### Frame by Frame

```
Frame 0 (0-0.5s): 截取初始状态
┌─────────────────────────────────────┐
│  ● AgentTrace - Reality Fork       │
│                                     │
│  [Run Agent]  ← 高亮按钮            │
│                                     │
│  Status: Ready                      │
└─────────────────────────────────────┘

Frame 1 (0.5-1.5s): 节点出现
┌─────────────────────────────────────┐
│  ┌──────┐                           │
│  │START │                           │
│  └──────┘                           │
│       │                             │
│  ┌──────┐                           │
│  │REASON│ ← 节点出现动画             │
│  └──────┘                           │
│       │                             │
│  ┌──────┐                           │
│  │TOOL  │                           │
│  └──────┘                           │
│       │                             │
│  ┌──────┐                           │
│  │RESULT│ ← 关键节点，高亮            │
│  │NORMAL│                           │
│  └──────┘                           │
└─────────────────────────────────────┘

Frame 2 (1.5-3s): Inspector 打开
┌─────────────────────────────────────┐
│  ┌──────┐         ┌─────────────┐   │
│  │TOOL  │─────────→│ Node: TOOL  │   │
│  └──────┘         │ result:     │   │
│       │           │ "CASE_NORM" │   │
│  ┌──────┐         └─────────────┘   │
│  │RESULT│              ↑            │
│  │NORMAL│         [修改这里]         │
│  └──────┘         ┌─────────────┐   │
│                   │[CASE_CRIT] │   │
│                   └─────────────┘   │
└─────────────────────────────────────┘

Frame 3 (3-4.5s): 动画 - 分支开始
┌─────────────────────────────────────┐
│     ╔═══════════╗                   │
│     ║   SPLIT    ║ ← 分叉特效        │
│     ╚═══════════╝                   │
│    ↙              ↘                 │
│ ┌──────┐     ┌──────┐               │
│ │ORIGIN│     │FORK  │              │
│ │(dim) │     │(glow)│ ← 绿光        │
│ │ gry  │     │green │              │
│ └──────┘     └──────┘               │
└─────────────────────────────────────┘

Frame 4 (4.5-6s): 结果展示
┌─────────────────────────────────────┐
│                                      │
│  ORIGINAL: "Rest and fluids"   [灰] │
│                                      │
│  FORKED: "CALL 911"  ← 红色大字      │
│                                      │
└─────────────────────────────────────┘
```

### GIF 技术要求

- **时长**: 6-8 秒
- **分辨率**: 800x450 (16:9)
- **格式**: MP4 → GIF 或直接 GIF
- **关键**: 不需要配音，文字直接打在画面上

---

## 📣 HackerNews / Reddit 发布文案

### 版本 A: HackerNews (更短更直接)

**Title** (最重要):

```
I built a tool that lets you edit any AI decision and watch reality fork into a new timeline
```

**Body**:

```
A week ago I had an idea: what if AI decisions weren't black boxes?

What if you could:
- See every step an AI took to reach a decision
- Edit any step (e.g. change a tool result)
- Watch the AI "replay" with your edit and branch into a different future

That's what AgentTrace does.

The demo: A medical triage agent. 
- Original: "mild discomfort" → CASE_NORMAL → "Rest and fluids"
- Forked: "mild discomfort" → CASE_CRITICAL → "CALL 911"

One edit. Two futures.

Code: https://github.com/yourname/AgentTrace
Demo: http://localhost:8765

Built with FastAPI + WebSockets + D3.js.
Deterministic replay engine + step-level mutation is the core trick.

Thoughts on where this goes? Editable AI cognition, branching reasoning, causal debugging?
```

---

### 版本 B: Reddit (更讲故事)

**Subreddit**: r/programming / r/MachineLearning / r/artificial

**Title**:

```
I made AI decisions editable — watch one edit fork "rest and fluids" into "CALL 911"
```

**Body**:

```
Two weeks ago I was debugging an AI agent and thought:

"Wouldn't it be wild if I could just... change one decision, and watch the AI's future completely change?"

So I built it.

**AgentTrace** — an AI decision timeline editor that visualizes agent reasoning as an interactive graph. Click any step. Edit it. Watch reality fork.

The demo is a medical triage agent. The moment that convinced me this was real:

```
Original path:
Patient: "mild discomfort"
→ Tool result: CASE_NORMAL
→ AI says: "Rest and fluids"

Forked path (I changed ONE word):
Patient: "mild discomfort"
→ Tool result: CASE_CRITICAL
→ AI says: "CALL 911 EMERGENCY"
```

This isn't just a demo. The core engine (snapshot + edit + replay + branch) works for any ReAct-style agent.

I think we're moving toward "AI as controllable simulation system" — editable cognition, branching futures, causal debugging.

Would love feedback on where this goes next.

GitHub: [link]
Live demo: [link]
```

---

## 🎯 Launch Strategy

| 渠道 | 策略 | 时间 |
|------|------|------|
| GitHub | 先发布，GIF + README | Day 1 |
| Twitter/X | 1 GIF + 1 sentence | Day 1 |
| HackerNews | 直接 post，不要 DM | Day 2 |
| Reddit | 选 r/programming，等 6am PST | Day 2-3 |
| LinkedIn | 更 business 版本 | Day 3 |

**关键**: GitHub 先上线，GIF 先准备好，launch 不要等完美。