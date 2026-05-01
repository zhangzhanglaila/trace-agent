"""Research Agent — multi-step research pipeline with tool calling, memory, and branching.

Usage:
    agent = ResearchAgent()
    result = agent.run("climate change impact on renewable energy")

    # With zero-invasion tracing:
    from agent_obs import dev
    dev(agent, "AI safety regulations", "database performance")

The agent follows a 5-step pipeline:
    search → extract_facts → verify_facts → analyze_sentiment → summarize

When the BUG is active (PLANNER_BUG_ENABLED=True), queries that return 4+
search results will skip the extract_facts and verify_facts steps, routing
directly to summarize with raw search data. This produces incomplete results.

Queries that trigger the bug: "AI", "machine learning" (5 results)
Queries that don't: "database", "SQL" (2 results), "climate" (3 results)
"""

from demo_agent.memory import AgentMemory
from demo_agent.planner import plan_next, PLANNER_BUG_ENABLED
from demo_agent.tools import (
    web_search,
    extract_facts,
    analyze_sentiment,
    verify_facts,
    query_knowledge_base,
)


class ResearchAgent:
    """Multi-step research agent with tool calling pipeline."""

    def __init__(self, enable_bug: bool = True, max_steps: int = 8):
        self.enable_bug = enable_bug
        self.max_steps = max_steps
        self.memory = AgentMemory()

    def run(self, query: str) -> str:
        """Run the full research pipeline for a query."""
        # Apply bug setting to planner module
        try:
            from demo_agent import planner as _planner
            _planner.PLANNER_BUG_ENABLED = self.enable_bug
        except Exception:
            pass

        self.memory.clear()
        self.memory.set("topic", query)

        step_count = 0

        while step_count < self.max_steps:
            step_count += 1

            # Decide next action
            plan = plan_next(self.memory)
            tool_name = plan.get("tool", "done")
            tool_args = plan.get("args", {})

            if tool_name == "done":
                break

            # Execute the tool with trace span if tracing is active
            result = self._call_tool_traced(tool_name, tool_args)

            # Store result in memory
            self._store_result(tool_name, result)

            # Check for error / empty results
            if isinstance(result, dict) and result.get("status") == "error":
                return f"[FAIL] {tool_name}: {result.get('error', 'unknown error')}"

        # Build final output
        return self._build_output()

    def _call_tool_traced(self, name: str, args: dict) -> dict:
        """Call a tool by name, with trace span if AgentTrace is active."""
        try:
            from agent_obs.trace_core import trace_span, SEM
        except ImportError:
            return self._call_tool(name, args)

        with trace_span(name, SEM.TOOL, inputs=args) as span:
            result = self._call_tool(name, args)
            span["outputs"] = {
                "result": result,
                **{k: str(v)[:200] for k, v in result.items() if k != "result"},
            }
            span["produces"] = {"tool_result": result}
            span["consumes"] = args
            return result

    def _call_tool(self, name: str, args: dict) -> dict:
        """Call a tool by name with args."""
        tools = {
            "web_search": web_search,
            "extract_facts": extract_facts,
            "analyze_sentiment": analyze_sentiment,
            "verify_facts": verify_facts,
            "query_knowledge_base": query_knowledge_base,
            "summarize": lambda **kw: self._summarize(**kw),
        }
        if name not in tools:
            return {"status": "error", "error": f"Unknown tool: {name}"}
        try:
            return tools[name](**args)
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _store_result(self, tool_name: str, result: dict):
        """Store tool result in memory under an appropriate key."""
        key_map = {
            "web_search": "search_results",
            "extract_facts": "facts",
            "verify_facts": "verified_facts",
            "analyze_sentiment": "sentiment",
            "summarize": "summary",
            "query_knowledge_base": "kb_data",
        }
        key = key_map.get(tool_name, tool_name)
        self.memory.set(key, result)

    def _summarize(self, **kwargs) -> dict:
        """Internal summarize tool — produces the final research summary."""
        source = kwargs.get("source", "")
        if source == "raw_search_results":
            # BUG PATH: summarizing raw search results without fact extraction
            search_data = kwargs.get("search_data", {})
            results = search_data.get("results", []) if isinstance(search_data, dict) else []
            snippets = [r.get("snippet", "") for r in results[:3]]
            summary = (
                "Based on initial search results, the topic appears to be active. "
                + " ".join(snippets)[:300]
                + " [WARNING: summary produced from raw search data — "
                + "facts were not extracted or verified]"
            )
            return {
                "summary": summary,
                "source": "raw_search",
                "fact_count": 0,
                "verified_count": 0,
                "completeness": "incomplete",
            }

        # CORRECT PATH: full pipeline with facts, verification, sentiment
        topic = kwargs.get("topic", "the topic")
        facts_data = kwargs.get("facts", {})
        verified_data = kwargs.get("verified", {})
        sentiment_data = kwargs.get("sentiment", {})

        facts = facts_data.get("facts", []) if isinstance(facts_data, dict) else []
        verified_count = verified_data.get("verified_count", 0) if isinstance(verified_data, dict) else 0
        sentiment = sentiment_data.get("sentiment", "neutral") if isinstance(sentiment_data, dict) else "neutral"

        if not facts:
            return {
                "summary": f"No facts were extracted for '{topic}'. Research incomplete.",
                "source": "facts",
                "fact_count": 0,
                "verified_count": 0,
                "completeness": "empty",
            }

        fact_lines = [f"- [{f.get('confidence', '?')}] {f.get('claim', '')}" for f in facts[:5]]
        summary = (
            f"Research on '{topic}' found {len(facts)} facts "
            f"({verified_count} verified against knowledge base). "
            f"Overall sentiment: {sentiment}. "
            + "Key findings: " + "; ".join(fact_lines)
        )
        return {
            "summary": summary[:500],
            "source": "facts",
            "fact_count": len(facts),
            "verified_count": verified_count,
            "sentiment": sentiment,
            "completeness": "complete" if verified_count > 0 else "partial",
        }

    def _build_output(self) -> str:
        """Build the final output string."""
        summary_data = self.memory.get("summary")
        if not summary_data:
            return "[PARTIAL] Research pipeline did not produce a summary."

        completeness = summary_data.get("completeness", "unknown")
        summary = summary_data.get("summary", "")

        if completeness == "incomplete":
            return f"[PARTIAL] {summary}"
        elif completeness == "empty":
            return f"[EMPTY] {summary}"
        else:
            return f"[OK] {summary}"
