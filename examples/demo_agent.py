"""
Semantically-rich demo agent for CLI testing of causal explanation.

Usage:
    python -m agent_obs.cli_main debug examples/demo_agent.py -i "weather in paris" -j "weather in mars"
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_obs.instrument import trace_tool
from agent_obs.trace_core import trace_span, trace_decision, SEM


# ============================================================
# Tools
# ============================================================

@trace_tool("weather", produces_key="weather_data")
def weather(city: str) -> str:
    db = {"paris": "Paris: 18C, cloudy", "tokyo": "Tokyo: 22C", "mars": "No data"}
    return db.get(city.lower(), f"No data for {city}")


@trace_tool("search", produces_key="search_result")
def search(query: str) -> str:
    kb = {"paris": "Capital of France", "tokyo": "Capital of Japan"}
    for k, v in kb.items():
        if k in query.lower():
            return v
    return f"No info for: {query}"


# ============================================================
# Agent with full semantic instrumentation
# ============================================================

class Agent:
    """An agent with LLM classification, decision routing, and fallback."""

    def run(self, query: str) -> str:
        q = query.lower()

        # Step 1: Classify intent (LLM call)
        with trace_span("classify_intent", SEM.LLM,
                        inputs={"prompt": query}) as s:
            if "weather" in q:
                intent = "weather"
            elif "search" in q or "what" in q or "who" in q:
                intent = "search"
            else:
                intent = "unknown"
            s["outputs"] = {"result": intent}
            s["produces"] = {"intent": intent}

        # Step 2: Route based on intent
        if intent == "weather":
            city = "paris"
            for c in ["paris", "tokyo", "mars", "london"]:
                if c in q:
                    city = c
                    break

            # Decision: should we call weather API?
            trace_decision("should_call_weather", value=True,
                           consumes={"intent": intent},
                           true_branch="call_weather_api",
                           false_branch="use_search_fallback")
            result = weather(city)

        elif intent == "search":
            trace_decision("should_call_search", value=True,
                           consumes={"intent": intent},
                           true_branch="call_search",
                           false_branch="use_default")
            result = search(query)

        else:
            trace_decision("unknown_intent_fallback", value=False,
                           consumes={"intent": intent},
                           true_branch="direct_answer",
                           false_branch="use_search_fallback")
            result = search(query)

        # Step 3: Check result quality
        is_good = "No " not in result and "Error" not in result
        trace_decision("result_sufficient", value=is_good,
                       consumes={"result": result},
                       true_branch="return_result",
                       false_branch="try_fallback")

        if not is_good:
            result = search(query)

        return result


# Convention: expose 'agent' variable
agent = Agent()
