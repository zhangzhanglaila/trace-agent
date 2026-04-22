"""
AgentTrace SDK - TraceWrapper
Wraps any Python agent and records execution traces.

Usage:
    from agent_obs import trace

    # Wrap any agent with a run(query) method
    traced_agent = trace(my_agent)

    result = await traced_agent.run("query")
"""

import asyncio
from typing import List, Dict
from dataclasses import asdict

from .emitter import EventEmitter


class TraceWrapper:
    """
    Wraps a Python agent and records its execution trace.

    The agent should implement a ReAct-style loop with:
    - run(query) - main entry point
    - llm_think(messages) - returns dict with action/action_input
    - call_tool(tool_name, args) - executes tools

    Usage:
        agent = MyAgent()
        traced = trace(agent)
        result = await traced.run("query")
    """

    def __init__(
        self,
        agent,
        trace_id: str = "agent",
        ws_sender=None,
        record_state: bool = True
    ):
        self.agent = agent
        self.trace_id = trace_id
        self.emitter = EventEmitter(trace_id=trace_id, ws_sender=ws_sender)
        self.record_state = record_state

        # Get agent's max_steps (default 10)
        self.max_steps = getattr(agent, 'max_steps', 10)

        # Store original run method
        self._original_run = getattr(agent, 'run', None)

        # Replace agent.run with traced version
        agent.run = self._traced_run

        # Store reference on agent
        agent._emitter = self.emitter
        agent._trace_id = trace_id

    async def _traced_run(self, query: str) -> str:
        """Traced run method - wraps the agent's run with tracing."""
        # First, emit session start
        await self._emit("session_start", {"query": query})

        # Now call the original run method
        # The original run does the actual agent loop
        try:
            result = await self._original_run(query)
            await self._emit("final_answer", {"answer": result})
            return result
        except Exception as e:
            return f"Error: {str(e)}"

    async def _emit(self, event_type: str, data: dict):
        """Emit event through the emitter."""
        await self.emitter.emit(event_type, data)

    def get_events(self) -> List[Dict]:
        """Get all recorded events."""
        return [asdict(e) for e in self.emitter.events]

    def get_messages(self) -> List[Dict]:
        """Get the final message history."""
        for event in reversed(self.emitter.events):
            if event.type == "state_snapshot":
                return event.data.get("messages", [])
        return []

    async def run(self, query: str) -> str:
        """Run the traced agent. Alias for agent.run()."""
        return await self.agent.run(query)


def trace(agent, trace_id: str = "agent", **kwargs) -> TraceWrapper:
    """
    One-line function to wrap an agent with tracing.

    Usage:
        traced_agent = trace(my_agent)
        traced_agent = trace(my_agent, trace_id="my-agent")
    """
    return TraceWrapper(agent, trace_id=trace_id, **kwargs)