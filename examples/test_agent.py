"""Minimal test agent for CLI testing."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_obs.instrument import trace_tool
from agent_obs.trace_core import trace_span


@trace_tool("weather")
def weather(city: str) -> str:
    db = {"paris": "Paris: 18C, cloudy", "tokyo": "Tokyo: 22C", "mars": "No data"}
    return db.get(city.lower(), f"No data for {city}")


@trace_tool("search")
def search(query: str) -> str:
    kb = {"paris": "Capital of France", "tokyo": "Capital of Japan"}
    for k, v in kb.items():
        if k in query.lower():
            return v
    return f"No info for: {query}"


class Agent:
    def run(self, query: str) -> str:
        q = query.lower()

        if "weather" in q:
            city = "paris"
            for c in ["paris", "tokyo", "mars"]:
                if c in q:
                    city = c
                    break
            result = weather(city)
        else:
            result = search(query)

        # Branch on result
        is_good = "No " not in result
        if not is_good:
            result = search(query)

        return result


# Convention: expose 'agent' variable
agent = Agent()
