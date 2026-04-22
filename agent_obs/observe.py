"""One-line integration: agent = observe(agent)"""
from .emitter import EventEmitter
from .instrument.react import ReActInstrumentor


def observe(agent, name: str = "agent"):
    emitter = EventEmitter(trace_id=name)
    instrumentor = ReActInstrumentor(agent, emitter)

    original_run = agent.run

    async def instrumented_run(query):
        return await instrumentor.run(query)

    agent.run = instrumented_run
    agent._emitter = emitter
    agent._instrumentor = instrumentor

    return agent
