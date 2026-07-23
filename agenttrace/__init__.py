"""
AgentTrace — Chrome DevTools for AI Agents.

我们把 Agent 的执行变成可读的时间线与因果图，并解释「为什么」。

单次运行透明化（一行接入，别人 Agent 代码零改动）：
    from agenttrace import trace_run
    with trace_run("my_agent", html_path="run.html") as run:
        agent.invoke("...")
    print(run.status, run.summary)

或用装饰器：
    from agenttrace import observe
    @observe(html_path="run.html")
    def my_agent(query): ...

A/B 对比（换了输入就炸时定位根因）：
    from agenttrace import enable, dev
    enable()
"""

from agent_obs.enable import enable, dev
from agent_obs.run import trace_run, observe, RunHandle
from agent_obs.instrument.auto import trace_step as step

__all__ = ["enable", "dev", "trace_run", "observe", "RunHandle", "step"]
