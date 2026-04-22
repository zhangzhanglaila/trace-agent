"""
AgentTrace SDK Usage Examples

Example 1: Basic ReAct Agent
Example 2: Custom Tool Agent
Example 3: LangChain-style Agent
"""

import asyncio

# ============================================================
# Example 1: Basic ReAct Agent
# ============================================================

class MyReActAgent:
    """A simple ReAct-style agent."""

    def __init__(self):
        self.tools = {
            "search": self.search,
            "calculate": self.calculate,
        }
        self.max_steps = 10

    def search(self, query: str) -> str:
        """Search the web (simulated)."""
        return f"Results for '{query}': [Article 1, Article 2, Article 3]"

    def calculate(self, expression: str) -> str:
        """Evaluate math expression (simulated)."""
        try:
            result = eval(expression)
            return str(result)
        except:
            return "Error: invalid expression"

    async def llm_think(self, messages: list) -> dict:
        """Simulate LLM reasoning."""
        last_msg = messages[-1]["content"].lower() if messages else ""

        # Check for tool use intent
        if "search" in last_msg or "look up" in last_msg:
            return {
                "thought": "User wants to search",
                "action": "search",
                "action_input": {"query": last_msg.split("search")[-1].strip() or last_msg}
            }
        elif "calculate" in last_msg or "math" in last_msg or any(c in last_msg for c in "+-*/"):
            import re
            nums = re.findall(r'[\d]+', last_msg)
            if nums:
                expr = "".join(nums[:4])  # Take first 4 digits
                return {
                    "thought": "Need to calculate",
                    "action": "calculate",
                    "action_input": {"expression": expr}
                }

        return {
            "thought": "General response needed",
            "action": None,
            "content": "I can help you search or calculate. What would you like?"
        }

    async def call_tool(self, tool_name: str, args: dict) -> str:
        if tool_name in self.tools:
            return self.tools[tool_name](**args)
        return f"Unknown tool: {tool_name}"

    async def run(self, query: str):
        messages = [{"role": "user", "content": query}]
        for _ in range(self.max_steps):
            response = await self.llm_think(messages)
            if not response.get("action"):
                return response.get("content", "")
            result = await self.call_tool(response["action"], response.get("action_input", {}))
            messages.append({"role": "tool", "name": response["action"], "content": result})
        return "Max steps reached"


# ============================================================
# Example 2: Tool-Using Agent with Custom Tools
# ============================================================

class DataAnalysisAgent:
    """An agent that analyzes data using tools."""

    def __init__(self):
        self.tools = {
            "fetch_data": self.fetch_data,
            "analyze": self.analyze,
            "report": self.report,
        }
        self.max_steps = 15

    def fetch_data(self, source: str) -> str:
        return f"Data from {source}: [100 rows loaded]"

    def analyze(self, data: str, method: str = "summary") -> str:
        if method == "summary":
            return f"Analysis summary: mean=50, std=15"
        elif method == "regression":
            return f"Regression result: y = 2.5x + 10, R²=0.95"
        return "Unknown method"

    def report(self, findings: str) -> str:
        return f"Report generated: {findings[:50]}..."

    async def llm_think(self, messages: list) -> dict:
        last_msg = messages[-1]["content"].lower()

        if "fetch" in last_msg or "load" in last_msg:
            return {"action": "fetch_data", "action_input": {"source": "database"}}
        elif "analyze" in last_msg:
            return {"action": "analyze", "action_input": {"data": "current", "method": "summary"}}
        elif "report" in last_msg:
            return {"action": "report", "action_input": {"findings": "Key insights found"}}

        return {"action": None, "content": "I can fetch, analyze, or report. What do you need?"}

    async def call_tool(self, tool_name: str, args: dict) -> str:
        return self.tools[tool_name](**args) if tool_name in self.tools else "Unknown"

    async def run(self, query: str):
        messages = [{"role": "user", "content": query}]
        for _ in range(self.max_steps):
            resp = await self.llm_think(messages)
            if not resp.get("action"):
                return resp.get("content", "")
            result = await self.call_tool(resp["action"], resp.get("action_input", {}))
            messages.append({"role": "tool", "name": resp["action"], "content": result})
        return "Done"


# ============================================================
# Run Examples
# ============================================================

async def main():
    print("=" * 60)
    print("AgentTrace SDK Examples")
    print("=" * 60)

    # Example 1: Wrap a ReAct agent
    print("\n[1] Tracing a ReAct agent...")
    from agent_obs import trace

    agent1 = MyReActAgent()
    traced1 = trace(agent1, trace_id="react-agent")

    result1 = await traced1.run("search for AI trends 2026")
    print(f">>> {result1}")

    # Check trace
    events = traced1.get_events()
    print(f">>> Traced {len(events)} events")
    for e in events[:5]:
        print(f"    - {e['type']}: step {e['step']}")

    # Example 2: Trace a data analysis agent
    print("\n[2] Tracing a Data Analysis agent...")
    agent2 = DataAnalysisAgent()
    traced2 = trace(agent2, trace_id="data-agent")

    result2 = await traced2.run("fetch data and analyze it")
    print(f">>> {result2}")

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())