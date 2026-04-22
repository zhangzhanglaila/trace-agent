"""ReAct instrumentation - CRITICAL: uses role: 'tool', snapshots AFTER append"""
from ..emitter import EventEmitter


class ReActInstrumentor:
    def __init__(self, agent, emitter: EventEmitter):
        self.agent = agent
        self.emitter = emitter

    async def run(self, query: str) -> str:
        messages = [{"role": "user", "content": query}]
        await self.emitter.emit("session_start", {"query": query})

        max_steps = 10
        for step in range(max_steps):
            await self.emitter.wait_if_paused()  # Checkpoint 1

            await self.emitter.emit("reasoning", {"step": step})
            response = await self.agent.llm_think(messages)
            await self.emitter.emit("reasoning_complete", {
                "step": step,
                "thought": response.get("thought", ""),
                "action": response.get("action"),
                "action_input": response.get("action_input")
            })

            if not response.get("action"):
                await self.emitter.emit("final_answer", {"answer": response.get("content", "")})
                return response.get("content", "")

            await self.emitter.wait_if_paused()  # Checkpoint 2

            tool_name = response["action"]
            tool_args = response.get("action_input", {})
            await self.emitter.emit("tool_call", {"step": step, "tool": tool_name, "args": tool_args})

            result = await self.agent.call_tool(tool_name, tool_args)
            await self.emitter.emit("tool_result", {"step": step, "tool": tool_name, "result": result})

            # CRITICAL: Use role: "tool" with name field
            messages.append({"role": "tool", "name": tool_name, "content": result})

            # CRITICAL: Snapshot AFTER appending
            await self.emitter.emit("state_snapshot", {"step": step, "messages": messages.copy()})

            await self.emitter.wait_if_paused()  # Checkpoint 3

        return "Max steps"

    async def run_from_state(self, messages: list):
        """Real time travel - re-runs agent, not events."""
        max_steps = 10
        for step in range(max_steps):
            await self.emitter.wait_if_paused()

            response = await self.agent.llm_think(messages)
            await self.emitter.emit("reasoning_complete", {
                "step": step,
                "thought": response.get("thought", ""),
                "action": response.get("action"),
                "is_forked": True
            })

            if not response.get("action"):
                await self.emitter.emit("final_answer", {"answer": response.get("content", "")})
                return response.get("content", "")

            await self.emitter.wait_if_paused()

            tool_name = response["action"]
            tool_args = response.get("action_input", {})
            await self.emitter.emit("tool_call", {"step": step, "tool": tool_name, "args": tool_args})

            result = await self.agent.call_tool(tool_name, tool_args)
            await self.emitter.emit("tool_result", {"step": step, "tool": tool_name, "result": result})

            messages.append({"role": "tool", "name": tool_name, "content": result})

        return "Max steps"
