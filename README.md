<p align="center">
  <h1 align="center">AgentTrace</h1>
  <h3 align="center">Causal Debugger for AI Agents</h3>
  <h4 align="center">Not just observing traces — telling you "why"</h4>
</p>

<p align="center">
  <b>中文简介</b> · 让别人的 Agent 跑一次就能看清每一步、自动定位失败或卡点。
</p>

<p align="center">
  <b>English Intro</b> · Run someone's agent once and see every step, automatically locating failures or stuck points.
</p>

<p align="center">
  <a href="#中文文档"><b>中文文档</b></a> ·
  <a href="#English-Docs"><b>English Docs</b></a> ·
  <a href="#快速-start"><b>快速 Start</b></a> ·
  <a href="#Quick-Start"><b>Quick Start</b></a>
</p>

<p align="center">
  <b>Packaged as <code>agenttrace</code> on PyPI</b> ·
  <a href="https://github.com/yourusername/AgentTrace"><b>GitHub Repository</b></a>
</p>

---

# 中文文档

## 一句话定位

> **别人的 Agent 跑一次，就能看清每一步、自动定位失败或卡点；换了输入就炸了，能精确告诉你为什么。**

现有工具（LangSmith、Langfuse、Phoenix）能告诉你「发生了什么」。
AgentTrace 能让你**别人的 Agent 变透明**，并进一步告诉你「**为什么发生了**」。

```
单次运行 → 步骤时间线 → 健康分析 → 自动定位失败/卡点/慢
实时监控 → SSE 推送 → 进度条 → 卡住告警
A/B 对比 → 因果 Diff → 根因定位 → 人话解释 + 修复建议
```

---

## 快速 Start

```bash
pip install agenttrace
```

```python
from agenttrace import trace_run, observe

@observe  # 可选：装饰器换取更精确的步骤边界
def my_agent(question: str) -> str:
    # 你的 Agent 代码
    return answer

# 运行一次，自动生成报告（即使抛异常也会生成）
result = trace_run(my_agent, "帮我规划东京之旅")
# 报告路径：./reports/<timestamp>_trace.html
```

运行后自动生成 HTML 报告，不到 30 秒你会看到：

> **🟢 运行成功**（4 步，2255ms）
>
> **📖 步骤时间线**
> - ✅ LLM: classify_intent (861ms)
> - ✅ Tool: weather_api (694ms)
> - ✅ Tool: activity_search (520ms)
> - ✅ LLM: summarize (180ms)
>
> **🔍 健康状态**
> - 失败步骤：无
> - 卡点：无
> - 慢步骤：无（所有步骤在正常范围内）

不需要配置、不需要 API Key、不需要改别人 Agent 代码。

---

## 核心能力

### M1 · 单次运行透明化（P0）

别人的 Agent 跑**一次**，就能看清：

| 能力 | 说明 |
|------|------|
| **步骤时间线** | 每步名称、输入、输出、状态、耗时 |
| **失败定位** | 某步抛异常 → 自动标红，显示错误信息 |
| **卡点检测** | 运行未正常结束 → 标出最后执行到的步骤 |
| **慢步骤高亮** | 耗时异常偏高（相对中位数）→ 标黄 |
| **健康报告** | 结构化 JSON 协议（`SingleRunReport`） |
| **自包含视图** | 零依赖 HTML，状态徽章 + 时间线 + 高亮 |

### M2 · 实时监控运行中（P1）

Agent 正在跑时，像进度条一样实时看到走到哪一步：

| 能力 | 说明 |
|------|------|
| **步骤事件流** | 每步结束时立即回调（`TraceContext.on_step_end`） |
| **SSE 推送** | 服务器推送步骤事件（8766 端口） |
| **前端进度条** | 零依赖前端，实时展示进度 |
| **卡住告警** | 后台线程监控超时，自动推送告警 |

### M3 · A/B 对比深化（P2）

同一个 Agent、同样的 Prompt，换了输入就炸了——为什么？

| 能力 | 说明 |
|------|------|
| **因果图 Diff** | 两张执行图对齐，逐变量比较 |
| **根因定位** | 精确定位分叉点和根因变量 |
| **错误分类** | 基于结构化特征分类（超时 / Schema 不匹配 / 重试循环等） |
| **修复建议** | 模板化建议生成 |

---

## 使用方式

### 方式一：上下文管理器（推荐）

```python
from agenttrace import trace_run, observe

@observe
def my_agent(question: str) -> str:
    # 你的 Agent 代码
    return answer

result = trace_run(my_agent, "帮我规划东京之旅")
```

### 方式二：LangChain 无缝接入

```python
from agenttrace.adapters.langchain import enable
enable()

# 你的 LangGraph / LangChain Agent
result = agent.invoke("帮我规划东京之旅")
# 自动生成报告
```

### 方式三：CLI 命令行

```bash
# 运行并生成单次报告
python -m agent_obs.cli_main run my_agent.py -i "帮我规划东京之旅"

# A/B 对比
python -m agent_obs.cli_main diff run_a.json run_b.json
```

---

## 工作原理

### 核心管线（单次运行）

```
Agent 运行 → Trace 录制 → 执行图（IR）→ 健康分析 → SingleRunReport
                                        ↓
                                失败 / 卡点 / 慢步骤检测
                                        ↓
                                    HTML 视图
```

### 实时监控管线

```
Agent 运行 → 每步结束回调 → 事件队列 ──→ SSE 推送
                ↓              ↑
        超时监控线程 → 告警事件 ─┘
```

### A/B 对比管线

```
运行 A ──→ Trace 录制 ──→ 执行图 ──┐
                                    ├──→ 因果 Diff ──→ 根因 + 修复建议
运行 B ──→ Trace 录制 ──→ 执行图 ──┘
```

---

## 架构总览

```
                           AgentTrace

  Agent Code --> TracedAgent --> TraceCapture
                                         |
                                         v
                                  ExecutionGraph
                                (SSA + CFG + phi-nodes)
                                         |
          +------------------------------+------------------------------+
          v                              v                              v
   HealthAnalyzer                  TraceDiffer                   实时监控
  (失败/卡点/慢步骤检测)            (因果 Diff)                (SSE + 告警)
          |                              |                              |
          +------------------------------+------------------------------+
                                         |
                                         v
                                  前端视图
                        (单次运行 HTML / Vue DevTools)
```

### 核心模块

| 模块 | 作用 |
|------|------|
| **TraceContext** | 录制内核：步骤捕获、状态管理、事件回调 |
| **ExecutionGraph** | 执行图 IR：SSA、控制流图、φ-节点 |
| **HealthAnalyzer** | 健康分析器：失败步骤 / 卡点 / 慢步骤检测 |
| **TraceDiffer** | A/B 对比：图对齐 Diff、因果判定、错误分类 |
| **DiffRenderer** | 渲染器：单次视图 / Diff 视图 / 多种格式 |
| **SSE 推送服务器** | 实时监控：步骤事件推送、进度条、告警 |

---

## 项目结构

```
AgentTrace/
├── agenttrace/                     # 公开 API 入口
│   └── __init__.py                 # from agenttrace import trace_run, observe
├── agent_obs/                      # 核心引擎
│   ├── enable.py                   # trace_run / @observe
│   ├── trace_core.py               # TraceContext + 录制内核
│   ├── execution_graph.py          # 执行图 IR
│   ├── health.py                   # HealthAnalyzer
│   ├── single_run.py               # SingleRunReport 构建
│   ├── single_run_view.py          # 单次运行 HTML 视图
│   ├── stream_server.py            # SSE 推送服务器（实时监控）
│   ├── timeout_watcher.py           # 卡住告警
│   ├── trace_diff.py               # TraceDiffer（A/B 对比）
│   ├── diagnosis.py                # 错误分类
│   ├── variable_analysis.py         # 变量分析
│   ├── diff_renderer.py            # Diff 渲染器
│   ├── trace_export.py             # TraceExport
│   ├── frontend_adapter.py         # 前端协议适配
│   ├── cli_main.py                 # CLI 入口
│   └── adapters/
│       └── langchain.py            # LangChain 适配器
├── examples/
│   ├── single_run_langgraph.py     # 单次运行演示
│   ├── streaming_demo.py           # 实时监控演示
│   └── travel_planner.py           # A/B 对比演示
├── tests/                          # 单元测试（84+ 项）
├── docs/                           # 文档
│   ├── 01-产品需求.md
│   ├── 02-技术架构.md
│   ├── 03-设计规范.md
│   └── 04-开发路线图.md
├── agent-trace-ui/                 # Vue 3 前端（可选）
└── pyproject.toml
```

---

## 开发进度

- ✅ **M1 单次运行透明化**（6/6 完成）
  - ✅ M1.1: SingleRunReport 协议
  - ✅ M1.2: HealthAnalyzer
  - ✅ M1.3: LangChain 接入验证
  - ✅ M1.4: 自包含 HTML 视图
  - ✅ M1.5: `trace_run` / `@observe`
  - ⬜ M1.6: 融入 Vue DevTools（暂缓）

- ✅ **M2 实时监控运行中**（3/3 完成）
  - ✅ M2.1: 步骤事件流
  - ✅ M2.2: SSE 推送 + 前端进度条
  - ✅ M2.3: 卡住告警

- ✅ **M3 A/B 对比深化**（4/4 完成）
  - ✅ M3.1: 因果链自动集成
  - ✅ M3.2: 错误分类强化
  - ✅ M3.3: 变量分析健壮化
  - ✅ M3.4: 渲染整合与测试

详见 [docs/04-开发路线图.md](docs/04-开发路线图.md)

---

<p align="center">
  <b>让别人在开发自己的 Agent 时，能真正看清 Agent 内部——跑到哪一步、卡在哪、为什么失败。</b>
</p>

---

# English Docs

## One-Line Pitch

> **Run someone's agent once and see every step, automatically locating failures or stuck points. When the same agent fails with different inputs, pinpoint exactly why.**

Existing tools (LangSmith, Langfuse, Phoenix) tell you "what happened."
AgentTrace makes **others' agents transparent** and further tells you **"why it happened."**

```
Single Run → Step Timeline → Health Analysis → Auto-locate Failure/Stuck/Slow
Real-time Monitor → SSE Push → Progress Bar → Stuck Alert
A/B Comparison → Causal Diff → Root Cause → Human Explanation + Fix Suggestions
```

---

## Quick Start

```bash
pip install agenttrace
```

```python
from agenttrace import trace_run, observe

@observe  # Optional: decorator for more precise step boundaries
def my_agent(question: str) -> str:
    # Your agent code
    return answer

# Run once, auto-generate report (even if exception is raised)
result = trace_run(my_agent, "Help me plan a trip to Tokyo")
# Report path: ./reports/<timestamp>_trace.html
```

After running, an HTML report is automatically generated. Within 30 seconds you'll see:

> **🟢 Run Success** (4 steps, 2255ms)
>
> **📖 Step Timeline**
> - ✅ LLM: classify_intent (861ms)
> - ✅ Tool: weather_api (694ms)
> - ✅ Tool: activity_search (520ms)
> - ✅ LLM: summarize (180ms)
>
> **🔍 Health Status**
> - Failed steps: None
> - Stuck point: None
> - Slow steps: None (all steps within normal range)

No configuration, no API key, no need to modify others' agent code.

---

## Core Capabilities

### M1 · Single Run Transparency (P0)

Run someone's agent **once** and see everything:

| Capability | Description |
|-----------|-------------|
| **Step Timeline** | Step name, input, output, status, latency |
| **Failure Location** | Step throws exception → auto-mark red, show error info |
| **Stuck Detection** | Run didn't finish properly → mark last executed step |
| **Slow Step Highlight** | Abnormally high latency (relative to median) → mark yellow |
| **Health Report** | Structured JSON protocol (`SingleRunReport`) |
| **Self-contained View** | Zero-dependency HTML, status badges + timeline + highlights |

### M2 · Real-time Monitor (P1)

When agent is running, see real-time progress like a progress bar:

| Capability | Description |
|-----------|-------------|
| **Step Event Stream** | Immediate callback on each step end (`TraceContext.on_step_end`) |
| **SSE Push** | Server push step events (port 8766) |
| **Frontend Progress Bar** | Zero-dependency frontend, real-time progress display |
| **Stuck Alert** | Background thread monitors timeout, auto-push alerts |

### M3 · A/B Comparison Deepening (P2)

Same agent, same prompt, fails with different inputs — why?

| Capability | Description |
|-----------|-------------|
| **Causal Graph Diff** | Align two execution graphs, compare variable by variable |
| **Root Cause Location** | Precisely locate divergence point and root cause variable |
| **Error Classification** | Structured feature-based classification (timeout / schema mismatch / retry loop, etc.) |
| **Fix Suggestions** | Template-based suggestion generation |

---

## Usage

### Method 1: Context Manager (Recommended)

```python
from agenttrace import trace_run, observe

@observe
def my_agent(question: str) -> str:
    # Your agent code
    return answer

result = trace_run(my_agent, "Help me plan a trip to Tokyo")
```

### Method 2: LangChain Seamless Integration

```python
from agenttrace.adapters.langchain import enable
enable()

# Your LangGraph / LangChain agent
result = agent.invoke("Help me plan a trip to Tokyo")
# Auto-generate report
```

### Method 3: CLI

```bash
# Run and generate single report
python -m agent_obs.cli_main run my_agent.py -i "Help me plan a trip to Tokyo"

# A/B comparison
python -m agent_obs.cli_main diff run_a.json run_b.json
```

---

## How It Works

### Core Pipeline (Single Run)

```
Agent Run → Trace Recording → Execution Graph (IR) → Health Analysis → SingleRunReport
                                                  ↓
                                  Failure / Stuck / Slow Step Detection
                                                  ↓
                                              HTML View
```

### Real-time Monitor Pipeline

```
Agent Run → Per-step Callback → Event Queue ──→ SSE Push
                ↓                   ↑
        Timeout Monitor Thread → Alert Event ─┘
```

### A/B Comparison Pipeline

```
Run A ──→ Trace Recording ──→ Execution Graph ──┐
                                          ├──→ Causal Diff ──→ Root Cause + Fix Suggestions
Run B ──→ Trace Recording ──→ Execution Graph ──┘
```

---

## Architecture Overview

```
                           AgentTrace

  Agent Code --> TracedAgent --> TraceCapture
                                         |
                                         v
                                  ExecutionGraph
                                (SSA + CFG + phi-nodes)
                                         |
          +------------------------------+------------------------------+
          v                              v                              v
   HealthAnalyzer                  TraceDiffer               Real-time Monitor
  (Failure/Stuck/Slow Detection)    (Causal Diff)             (SSE + Alert)
          |                              |                              |
          +------------------------------+------------------------------+
                                         |
                                         v
                                  Frontend View
                        (Single Run HTML / Vue DevTools)
```

### Core Modules

| Module | Purpose |
|--------|---------|
| **TraceContext** | Recording kernel: step capture, state management, event callbacks |
| **ExecutionGraph** | Execution graph IR: SSA, CFG, φ-nodes |
| **HealthAnalyzer** | Health analyzer: failure / stuck / slow step detection |
| **TraceDiffer** | A/B comparison: graph alignment diff, causal judgment, error classification |
| **DiffRenderer** | Renderer: single view / diff view / multiple formats |
| **SSE Push Server** | Real-time monitor: step event push, progress bar, alerts |

---

## Project Structure

```
AgentTrace/
├── agenttrace/                     # Public API entry
│   └── __init__.py                 # from agenttrace import trace_run, observe
├── agent_obs/                      # Core engine
│   ├── enable.py                   # trace_run / @observe
│   ├── trace_core.py               # TraceContext + recording kernel
│   ├── execution_graph.py          # Execution graph IR
│   ├── health.py                   # HealthAnalyzer
│   ├── single_run.py               # SingleRunReport builder
│   ├── single_run_view.py          # Single run HTML view
│   ├── stream_server.py            # SSE push server (real-time monitor)
│   ├── timeout_watcher.py           # Stuck alert
│   ├── trace_diff.py               # TraceDiffer (A/B comparison)
│   ├── diagnosis.py                # Error classification
│   ├── variable_analysis.py         # Variable analysis
│   ├── diff_renderer.py            # Diff renderer
│   ├── trace_export.py             # TraceExport
│   ├── frontend_adapter.py         # Frontend protocol adapter
│   ├── cli_main.py                 # CLI entry
│   └── adapters/
│       └── langchain.py            # LangChain adapter
├── examples/
│   ├── single_run_langgraph.py     # Single run demo
│   ├── streaming_demo.py           # Real-time monitor demo
│   └── travel_planner.py           # A/B comparison demo
├── tests/                          # Unit tests (84+ items)
├── docs/                           # Documentation
│   ├── 01-产品需求.md
│   ├── 02-技术架构.md
│   ├── 03-设计规范.md
│   └── 04-开发路线图.md
├── agent-trace-ui/                 # Vue 3 frontend (optional)
└── pyproject.toml
```

---

## Development Progress

- ✅ **M1 Single Run Transparency** (6/6 complete)
  - ✅ M1.1: SingleRunReport protocol
  - ✅ M1.2: HealthAnalyzer
  - ✅ M1.3: LangChain integration validation
  - ✅ M1.4: Self-contained HTML view
  - ✅ M1.5: `trace_run` / `@observe`
  - ⬜ M1.6: Vue DevTools integration (deferred)

- ✅ **M2 Real-time Monitor** (3/3 complete)
  - ✅ M2.1: Step event stream
  - ✅ M2.2: SSE push + frontend progress bar
  - ✅ M2.3: Stuck alert

- ✅ **M3 A/B Comparison Deepening** (4/4 complete)
  - ✅ M3.1: Causal chain auto-integration
  - ✅ M3.2: Error classification strengthening
  - ✅ M3.3: Variable analysis robustization
  - ✅ M3.4: Rendering integration and testing

See [docs/04-开发路线图.md](docs/04-开发路线图.md) for details.

---

<p align="center">
  <b>Let others truly see inside their agents during development — which step it reached, where it got stuck, why it failed.</b>
</p>

---

<p align="center">
  <img src="https://img.shields.io/badge/Language-TypeScript-blue" alt="TypeScript">
  <img src="https://img.shields.io/badge/Language-Python-yellow" alt="Python">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License">
  <img src="https://img.shields.io/badge/PyPI-agenttrace-orange" alt="PyPI">
</p>

<p align="center">
  <b>Topics:</b>
  <a href="https://github.com/topics/agent">agent</a> ·
  <a href="https://github.com/topics/debugger">debugger</a> ·
  <a href="https://github.com/topics/trace">trace</a> ·
  <a href="https://github.com/topics/langchain">langchain</a> ·
  <a href="https://github.com/topics/ai">ai</a> ·
  <a href="https://github.com/topics/causal-inference">causal-inference</a> ·
  <a href="https://github.com/topics/execution-graph">execution-graph</a> ·
  <a href="https://github.com/topics/health-monitoring">health-monitoring</a> ·
  <a href="https://github.com/topics/sse">sse</a> ·
  <a href="https://github.com/topics/real-time">real-time</a>
</p>

---

## License

MIT

---

**Language / 语言:** [简体中文](#中文文档) | [English](#English-Docs)
