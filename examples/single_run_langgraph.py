"""
M1.3 验证 / 示例：真实 LangGraph Agent 的「单次运行透明化」。

证明：别人用 LangChain/LangGraph 写的 Agent，只跑一次（不依赖 A/B 对比），
就能通过 AgentTrace 拿到一份可读的步骤时间线 + 自动定位失败/卡点。

运行（DeepSeek，OpenAI 兼容接口）：
    DEEPSEEK_API_KEY=sk-xxx python examples/single_run_langgraph.py

无 key 时自动降级为 mock LLM，仍可跑通全链路（可复现、不烧钱）。
"""

import os
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

# AgentTrace：一次性接管（零改动用户 Agent 逻辑）
from agent_obs.instrument.auto import auto_trace
from agent_obs.trace_core import trace_root, trace_span, SEM
from agent_obs.single_run import build_single_run_report
from agent_obs.health import analyze_health


# ── 用户的 Agent（对 AgentTrace 无感知） ──

class State(TypedDict, total=False):
    query: str
    intent: str
    weather: str
    answer: str


def _make_llm():
    """DeepSeek(OpenAI 兼容)；无 key 则用 mock。"""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        from langchain_core.language_models.fake_chat_models import FakeListChatModel
        return FakeListChatModel(responses=["weather", "东京今天天气晴朗，适合出行。"])
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key=key,
        temperature=0,
        max_tokens=60,
    )


def build_agent(fail_tool: bool = False):
    llm = _make_llm()

    def classify(state: State) -> State:
        msg = llm.invoke(f"用一个词判断这句话的意图(weather/other)：{state['query']}")
        intent = "weather" if "weather" in str(msg.content).lower() or "天气" in state["query"] else "other"
        return {"intent": intent}

    def search_weather(state: State) -> State:
        # 用户的工具调用，用 trace_span 标注为 TOOL 步骤
        with trace_span("weather_api", SEM.TOOL, inputs={"city": "东京"}) as span:
            if fail_tool:
                raise RuntimeError("天气服务连接超时 (simulated)")
            result = "晴 25°C"
            span["outputs"] = {"result": result}
            return {"weather": result}

    def respond(state: State) -> State:
        msg = llm.invoke(f"根据天气「{state.get('weather','')}」，用一句话回答：{state['query']}")
        return {"answer": str(msg.content)}

    g = StateGraph(State)
    g.add_node("classify", classify)
    g.add_node("search", search_weather)
    g.add_node("respond", respond)
    g.add_edge(START, "classify")
    g.add_edge("classify", "search")
    g.add_edge("search", "respond")
    g.add_edge("respond", END)
    return g.compile()


# ── 单次运行透明化：跑一次 → 报告 ──

def run_once(scenario: str, query: str, fail_tool: bool = False) -> dict:
    auto_trace()  # 幂等：patch LangChain BaseChatModel.invoke，激活捕获
    agent = build_agent(fail_tool=fail_tool)
    completed = True
    with trace_root(f"langgraph_{scenario}", auto_export=False) as ctx:
        try:
            agent.invoke({"query": query})
        except Exception as e:  # 运行被异常中断 → 供分析器判定卡点/失败
            completed = False
            print(f"  [!] 运行中断：{e}")
    report = build_single_run_report(ctx, run_id=scenario, run_name=f"langgraph_{scenario}")
    analyze_health(report, completed=completed)
    return report


def print_report(report: dict):
    print(f"\n{'='*60}")
    print(f"  运行报告：{report['run_name']}  ·  状态={report['status']}  ·  {report['step_count']} 步  ·  {report['duration_ms']}ms")
    print(f"{'='*60}")
    h = report["health"]
    for s in report["steps"]:
        mark = {"error": "[X]", "running": "[~]", "ok": "[OK]"}.get(s["status"], "[.]")
        flags = []
        if s["id"] == h["failed_step_id"]:
            flags.append("失败点")
        if s["id"] == h["stuck_step_id"]:
            flags.append("卡点")
        if s["id"] in h["slow_step_ids"]:
            flags.append("慢")
        tag = f"  <<< {'/'.join(flags)}" if flags else ""
        dur = f"{s['duration_ms']}ms" if s["duration_ms"] is not None else "-"
        print(f"  {mark:<4} [{s['kind']:<8}] {s['name'][:36]:<36} {dur:>10}{tag}")
    print(f"\n  >> 诊断：{h['summary']}")


if __name__ == "__main__":
    print(">> 场景 1：正常运行（应得健康报告）")
    print_report(run_once("ok", "东京今天天气怎么样？", fail_tool=False))

    print("\n\n>> 场景 2：工具抛错（应自动定位失败步骤）")
    print_report(run_once("fail", "东京今天天气怎么样？", fail_tool=True))
