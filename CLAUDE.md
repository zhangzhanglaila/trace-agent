# CLAUDE.md · AgentTrace 协作指引

本文件给 AI 协作者（Claude Code）与开发者提供**工作说明**与**标准文件路径**。
开始任何任务前，先读相关标准文档；有冲突时以 `docs/` 为准。

## 项目一句话

AgentTrace 是「AI Agent 的因果调试器」。当前重心：**让别人的 Agent 单次运行即透明**——
一次运行就能看清每一步、自动定位失败步骤与卡点。（历史能力：A/B 对比根因分析。）

## 标准文件路径（改动前必读）

| 文档 | 作用 |
|------|------|
| [docs/README.md](./docs/README.md) | 文档中心索引 |
| [docs/01-产品需求.md](./docs/01-产品需求.md) | 定位、用户、P0/P1/P2 需求、验收标准 |
| [docs/02-技术架构.md](./docs/02-技术架构.md) | 分层、核心文件、SingleRunReport 协议、扩展点 |
| [docs/03-设计规范.md](./docs/03-设计规范.md) | 编码/前端/测试/Git/文档规范 |
| [docs/04-开发路线图.md](./docs/04-开发路线图.md) | 里程碑与子步骤拆分、**当前进度** |
| [开发日志/](./开发日志/) | 每日完成事项与待办，见其 README |

## 工作说明（每次任务遵循）

1. **先看进度**：读 `docs/04-开发路线图.md` 的「当前进度」，确认当前该做哪个子步骤。
2. **先方案后编码**：新增能力先在 `01`/`04` 落定范围；跨前后端结构先在 `02` 定协议。
3. **小步推进**：一次只做一个可独立验证的子步骤，不一口气做完整个里程碑。**不确定就先与用户沟通**。
4. **零侵入优先**：面向用户的接入默认不要求改别人 Agent 代码；装饰器为进阶增强。
5. **测试与验证**：新分析器配单元测试；改录制内核跑 `test_v2_compiler.py`、`test_explain_engine.py`。
6. **收尾三件事**：
   - 更新 `docs/04-开发路线图.md` 对应子步骤状态与「当前进度」。
   - 在 `开发日志/YYYY-MM-DD.md` 记录当天完成事项与待办（无则新建当日文件）。
   - 涉及需求/架构变更时，更新对应文档底部「变更记录」。
7. **提交约定**：未经用户要求不提交/推送；需提交时先建分支，格式 `<type>: <简述>`。

## 关键代码位置

- 录制内核：`agent_obs/trace_core.py`
- 执行图 IR：`agent_obs/execution_graph.py`
- A/B 对比：`agent_obs/trace_diff.py`
- 前端协议适配：`agent_obs/frontend_adapter.py`
- 启用入口：`agent_obs/enable.py`（`enable()` / `dev()`）
- LangChain 适配器：`agent_obs/adapters/langchain.py`
- 前端：`agent-trace-ui/`（Vue 3 + `server.py`）
