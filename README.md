<p align="center">
  <h1 align="center">AgentTrace</h1>
  <h3 align="center">AI Agent 的因果调试器</h3>
  <h4 align="center">不只是看 Trace，而是告诉你「为什么」</h4>
</p>

<p align="center">
  <b>同一个 Agent，同样的 Prompt，换了输入就炸了？<br>AgentTrace 能精确告诉你：哪个变量变了、在哪一步分叉了、怎么修。</b>
</p>

<p align="center">
  <a href="#30-秒体验"><b>30 秒体验</b></a> ·
  <a href="#一行代码启用"><b>一行代码启用</b></a> ·
  <a href="#langchain-无缝接入"><b>LangChain 适配</b></a> ·
  <a href="#工作原理"><b>工作原理</b></a>
</p>

---

## 🎯 一句话定位

> **你的 Agent 在输入 A 上跑得好好的，换了输入 B 就炸了——为什么？**

现有工具（LangSmith、Langfuse、Phoenix）能告诉你「发生了什么」。
AgentTrace 能告诉你「**为什么发生了**」。

```
输入 A / B → 执行图构建 → 因果 Diff → 根因定位 → 人话解释 + 修复建议
```

---

## ⚡ 30 秒体验

```bash
pip install agenttrace
```

```python
from agenttrace import enable
enable()
```

打开 `http://127.0.0.1:8765`，点击 **运行 Demo**，不到 30 秒你会看到：

```
┌──────────────────────────────────────────────────┐
│  🔴 检测到 Bug                                    │
│                                                    │
│  📖 发生了什么                                     │
│  Agent 在「决定是否搜索活动」这一步分叉了：         │
│  运行 A 走了搜索路径，运行 B 直接跳过。            │
│                                                    │
│  🔍 根因                                          │
│  `weather current result`:                         │
│    运行 A → "clear"  ·  运行 B → "rain"            │
│  就是这个变量导致了整条链路的分叉。                 │
│                                                    │
│  💡 影响范围                                       │
│  分叉点：routing 决策  ·  运行 B 缺失了活动推荐    │
│         ↓ 查看完整分析                              │
└──────────────────────────────────────────────────┘
```

不需要配置、不需要 API Key、不需要改代码。第一次打开就能看到一个**真实的 Bug、它的根因、以及修复方向**。

---

## 🔌 LangChain 无缝接入

```python
from agenttrace.adapters.langchain import enable
enable()
```

一行代码，自动 patch `BaseChatModel.invoke()`，**所有** LangChain 生态的 Agent——LangGraph、langchain_openai、langchain_anthropic——全部自动接入，你的 Agent 代码零改动。

### 对比 LangSmith

| 能力 | AgentTrace | LangSmith |
|------|:---:|:---:|
| Trace 可视化 | ✅ | ✅ |
| 变量级根因分析 | ✅ | ❌ |
| 因果图 Diff | ✅ | ❌ |
| 「为什么分叉？」 | ✅ | ❌ |
| 反事实推理引擎 | ✅ | ❌ |
| 一行代码启用 | ✅ | ✅ |
| LangChain 生态 | ✅ | ✅ |

**LangSmith 告诉你「发生了什么」，AgentTrace 告诉你「为什么」。**

---

## 🧠 工作原理

### 核心管线

```
Agent 运行 A ──→ Trace 录制 ──→ 执行图 ──┐
                                          ├──→ 因果 Diff ──→ 根因 + 修复建议
Agent 运行 B ──→ Trace 录制 ──→ 执行图 ──┘
```

1. **Trace 录制** — 录制两次运行的完整细节：输入、输出、变量绑定、控制流
2. **执行图编译** — 每次运行被编译成确定性的 SSA 中间表示（带 CFG 和 φ-节点）
3. **因果 Diff** — 两张图对齐，逐变量比较，精确定位分叉点和根因变量
4. **Verdict + Fix** — 输出人话解释、诊断类型、置信度、修复建议

### 可检测的 Diff 类型

| 类型 | 检测什么 | 示例 |
|------|----------|------|
| `value_diverged` | 同一变量在两次运行中取值不同 | `weather = "clear"` vs `"rain"` |
| `tool_missed` | 运行 A 调了工具，运行 B 没调 | `activity_search` vs `summarize` |
| `branch_diverged` | 控制流走向不同 | true 路径 vs None 路径 |
| `output_partial` | 运行 B 输出不完整 | 缺少行程推荐段落 |

---

## 🚀 使用方式

### 方式一：一行代码启用（推荐）

```python
from agenttrace import enable, dev

# 自动挂载 —— 你的 Agent 会出现在 UI 的「已连接」列表中
enable(auto_attach=True)

# 或者用 dev() —— 自动运行两次、Diff、打开浏览器
dev(my_agent, "Tokyo", "Paris")
```

### 方式二：CLI 命令行

```bash
# Diff 两次运行
python -m agent_obs.cli_main debug my_agent.py \
  -i "帮我规划东京之旅" \
  -j "帮我规划巴黎之旅"

# 带 Trace 运行
python -m agent_obs.cli_main run my_agent.py -i "东京"
```

### 方式三：手动插桩

```python
from agent_obs.instrument import trace_llm, trace_tool, auto_trace

@trace_llm("classify_intent")
def classify(query: str) -> str: ...

@trace_tool("weather")
def weather_api(city: str) -> str: ...

auto_trace()  # 自动 patch OpenAI + LangChain SDK
```

---

## 🏗️ 架构总览

```
                            AgentTrace
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  Agent 代码 ──→ TracedAgent ──→ TraceCapture             │
│                                      │                   │
│                                      ▼                   │
│                               ExecutionGraph             │
│                            (SSA + CFG + φ-节点)          │
│                                      │                   │
│                     ┌────────────────┼──────────────┐    │
│                     ▼                ▼              ▼    │
│               SemanticResolver  AgentIR     SCM 引擎     │
│              (语义格解析)     (why/        (结构化        │
│                               what_if)     因果模型)     │
│                     │                │              │    │
│                     └────────────────┼──────────────┘    │
│                                      ▼                   │
│                               TraceDiffResult            │
│                          (根因 + 影响范围 + 修复建议)     │
│                                      │                   │
│                                      ▼                   │
│                          ┌──────────────────┐           │
│                          │  DevTools UI      │           │
│                          │ (Vue 3 + ECharts) │           │
│                          └──────────────────┘           │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### 核心引擎

| 模块 | 作用 |
|------|------|
| **ExecutionGraph** | 编译器级中间表示：SSA、控制流图、φ-节点、到达定义分析 |
| **AgentIR** | 语义查询层：`why(node)`「为什么走到这」/ `what_if(node, flip)`「如果翻转会怎样」/ `blame(variable)`「该怪谁」 |
| **SCM 引擎** | 结构化因果模型，支持介入和反事实推理 |
| **Trace Differ** | 图对齐 Diff，带因果角色匹配和影响评分 |

---

## 📂 项目结构

```
AgentTrace/
├── agenttrace/                     # 公开 API 入口
│   └── __init__.py                 # from agenttrace import enable, dev
├── agent_obs/                      # 核心引擎
│   ├── enable.py                   # enable() + dev()
│   ├── adapters/
│   │   └── langchain.py            # LangChain 适配器
│   ├── execution_graph.py          # 执行图 IR + SSA + CFG
│   ├── trace_core.py               # TracedAgent + TraceContext + 语义类型
│   ├── trace_diff.py               # TraceDiffer + 因果判定
│   ├── trace_export.py             # TraceExport（兼容 LangSmith 格式）
│   ├── cli_main.py                 # CLI：run / diff / debug
│   ├── frontend_adapter.py         # Trace → 统一 JSON 协议
│   └── instrument/
│       └── auto.py                 # OpenAI + LangChain 自动插桩
├── examples/
│   ├── travel_planner.py           # Demo：旅行规划器（含真实 Bug）
│   ├── buggy_agent.py              # 可配置的故障注入
│   ├── autonomous_agent.py         # 多工具推理 Agent
│   └── demo_cases.py               # 3 个杀手级调试案例
├── agent-trace-ui/                 # Vue 3 DevTools 前端
│   ├── src/components/             # 14 个 UI 组件
│   ├── src/store/traceStore.ts     # Pinia 状态管理
│   ├── src/types/trace.ts          # TypeScript 协议定义
│   └── server.py                   # API 服务 + 静态文件托管
├── pyproject.toml                  # pip install agenttrace
└── README.md
```

---

<p align="center">
  <b>为 AI 工程师打造——</b><br>
  <b>不是让你「看到」Agent，而是让你「理解」Agent。</b>
</p>

---

## 许可证

MIT
