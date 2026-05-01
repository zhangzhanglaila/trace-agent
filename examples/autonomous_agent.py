"""
Mini Autonomous Multi-Tool Agent — demo workload for AgentTrace.

Capabilities:
  - Tool Planning (LLM + deterministic rule fallback)
  - Multi-step reasoning with tool chaining
  - Memory store / retrieve across steps
  - Tool routing policy (deterministic rules → LLM fallback)

Tools: weather, search, python, memory_store, memory_retrieve

Usage:
    # Single run
    python -m agent_obs.cli_main run examples/autonomous_agent.py -i "Paris weather and running advice"

    # Causal debug: compare two runs
    python -m agent_obs.cli_main debug examples/autonomous_agent.py \
        -i "Paris weather + running advice" \
        -j "Tokyo weather + hiking advice"

    # Causal debug: compare correct vs error path
    python -m agent_obs.cli_main debug examples/autonomous_agent.py \
        -i "Calculate 2+2 then weather in Paris" \
        -j "Calculate 1/0 then weather in Mars"
"""
import sys
import os
import json
import re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_obs.trace_core import trace_span, trace_decision, SEM, TracedAgent


# ============================================================
# Tool implementations
# ============================================================

_WEATHER_DB = {
    "paris":     {"temp": 18, "condition": "cloudy", "humidity": 65, "wind": 12},
    "tokyo":     {"temp": 22, "condition": "sunny",  "humidity": 55, "wind": 8},
    "london":    {"temp": 12, "condition": "rainy",  "humidity": 80, "wind": 20},
    "new york":  {"temp": 25, "condition": "sunny",  "humidity": 50, "wind": 10},
    "beijing":   {"temp": 30, "condition": "hazy",   "humidity": 45, "wind": 5},
    "sydney":    {"temp": 20, "condition": "clear",  "humidity": 60, "wind": 15},
    "moscow":    {"temp": -5, "condition": "snow",   "humidity": 70, "wind": 25},
    "mars":      None,  # No data → triggers uncertainty
}

_SEARCH_KB = {
    "running": {
        "cloudy 18C":  "18C cloudy: excellent for running. Light jacket recommended.",
        "rainy 12C":   "12C rainy: not recommended for running. Indoor alternative suggested.",
        "sunny 22C":   "22C sunny: good for running. Stay hydrated.",
        "sunny 25C":   "25C sunny: warm for running. Go early morning.",
        "hazy 30C":    "30C hazy: avoid outdoor running. Air quality concern.",
        "clear 20C":   "20C clear: perfect running weather.",
        "snow -5C":    "-5C snow: dangerous for running. Use treadmill.",
    },
    "hiking": {
        "sunny 22C":   "22C sunny: ideal for hiking.",
        "rainy 12C":   "12C rainy: hiking not advised. Trails slippery.",
        "sunny 25C":   "25C sunny: good hiking. Bring water.",
        "cloudy 18C":  "18C cloudy: fine for hiking. Check rain forecast.",
        "clear 20C":   "20C clear: excellent hiking conditions.",
    },
    "general": {
        "uncertain": "Conditions uncertain. Recommend checking local forecast.",
    },
}


def tool_weather(city: str) -> dict:
    """Get weather data for a city."""
    city_key = city.lower().strip()
    data = _WEATHER_DB.get(city_key)
    if data is None:
        return {"city": city, "error": True,
                "message": f"No weather data for {city}",
                "uncertainty": "high"}
    return {"city": city, "error": False, **data}


def tool_search(query: str, context: dict = None) -> dict:
    """Search knowledge base for activity advice given weather."""
    q = query.lower()
    # Match activity
    activity = None
    for act in ["running", "hiking", "cycling", "walking"]:
        if act in q:
            activity = act
            break

    if not activity:
        return {"query": query, "error": False,
                "results": [_SEARCH_KB["general"]["uncertain"]]}

    # Match weather condition
    kb = _SEARCH_KB.get(activity, {})
    cond = context.get("condition", "") if context else ""
    temp = context.get("temp", 0) if context else 0
    temp_desc = f"{cond} {temp}C"

    advice = kb.get(temp_desc)
    if not advice:
        # Fuzzy match
        for key, val in kb.items():
            if cond in key.lower():
                advice = val
                break
    if not advice:
        advice = f"No specific {activity} advice for {temp_desc}. Use caution."

    return {"query": query, "activity": activity, "error": False,
            "results": [advice], "context_used": temp_desc}


def tool_python(code: str) -> dict:
    """Execute Python code safely and return result."""
    # Sanitize: only allow basic math and string ops
    safe_builtins = {
        "abs": abs, "round": round, "min": min, "max": max,
        "sum": sum, "len": len, "int": int, "float": float,
        "str": str, "bool": bool, "list": list, "dict": dict,
        "True": True, "False": False, "None": None,
    }
    try:
        # Only allow expressions, not statements
        code_clean = code.strip()
        if any(kw in code_clean for kw in ["import", "exec", "eval", "__", "open", "os."]):
            return {"error": True, "message": f"Blocked unsafe code: {code_clean[:50]}"}

        result = eval(code_clean, {"__builtins__": safe_builtins}, {})
        return {"error": False, "result": result, "code": code_clean}
    except Exception as e:
        return {"error": True, "message": str(e), "code": code_clean}


# In-memory store
_MEMORY: dict = {}

def tool_memory_store(key: str, value: any) -> dict:
    """Store a value in memory."""
    _MEMORY[key] = value
    return {"stored": True, "key": key, "value_preview": str(value)[:100]}


def tool_memory_retrieve(key: str) -> dict:
    """Retrieve a value from memory."""
    if key in _MEMORY:
        return {"found": True, "key": key, "value": _MEMORY[key]}
    # Partial match
    for k, v in _MEMORY.items():
        if key in k or k in key:
            return {"found": True, "key": k, "value": v, "partial_match": True}
    return {"found": False, "key": key}


# ============================================================
# Tool Router (deterministic rules + LLM fallback)
# ============================================================

def route_tool(query: str, context: dict, history: list) -> tuple:
    """
    Route query to the appropriate tool.

    Returns (tool_name, tool_args, routing_method, confidence).

    Priority:
    1. Deterministic rules (high confidence)
    2. Pattern matching (medium confidence)
    3. LLM planner (lower confidence, but flexible)
    """
    q = query.lower()

    # ── Rule 1: Math/code → python ──
    # Match expressions like "2+2", "3*4", "1/0" anywhere in the query
    math_expr = re.search(r'(\d+(?:\s*[+\-*/%]\s*\d+)+)', q)
    if math_expr:
        return ("python", {"code": math_expr.group(1).strip()},
                "deterministic", 0.95)

    # ── Rule 2: Explicit weather request → weather ──
    # Skip if we already fetched weather — let downstream rules or LLM handle the next step
    if not (context and "weather_data" in context) and \
       any(w in q for w in ["weather", "temperature", "forecast", "how hot", "how cold"]):
        city = "paris"  # default
        for c in _WEATHER_DB:
            if c in q:
                city = c
                break
        return ("weather", {"city": city}, "deterministic", 0.90)

    # ── Rule 3: Memory recall → memory_retrieve ──
    if any(w in q for w in ["recall", "remember", "previous", "what did i"]):
        key_match = re.search(r'(?:recall|remember|previous)\s+(.+)', q)
        key = key_match.group(1).strip() if key_match else "last_result"
        return ("memory_retrieve", {"key": key}, "deterministic", 0.85)

    # ── Rule 4: Search for advice → search ──
    if any(w in q for w in ["running", "hiking", "cycling", "advice", "good for",
                              "should i", "recommend", "suitable"]):
        weather_ctx = context.get("weather_data", {}) if context else {}
        return ("search", {"query": q, "context": weather_ctx},
                "deterministic", 0.80)

    # ── Rule 5: Store result → memory_store ──
    if any(w in q for w in ["save", "store", "remember this"]):
        return ("memory_store", {"key": "last_result", "value": str(context)},
                "deterministic", 0.80)

    # ── Fallback: LLM planner ──
    return _llm_plan(q, context, history)


def _llm_plan(query: str, context: dict, history: list) -> tuple:
    """LLM-based planning for ambiguous queries."""
    # Simulated LLM planning — in production this would call an actual LLM
    # The structured output simulates what an LLM would return
    q = query.lower()

    with trace_span("planner_llm", SEM.LLM,
                    inputs={"query": query, "context_preview": str(context)[:200]}) as span:
        # Simulate LLM reasoning
        plan = _simulate_llm_plan(q, context)
        span["outputs"] = {"result": json.dumps(plan)}
        span["produces"] = {"plan": plan}
        return (plan["tool"], plan["args"], "llm", 0.65)


def _simulate_llm_plan(query: str, context: dict) -> dict:
    """Simulate LLM planning output."""
    q = query.lower()

    # If we have weather data but no advice yet
    if context and "weather_data" in context:
        wd = context["weather_data"]
        if not wd.get("error"):
            return {"tool": "search",
                    "args": {"query": query, "context": wd},
                    "reason": "Weather data available, need activity advice"}

    # If context mentions uncertainty
    if context and context.get("uncertainty"):
        return {"tool": "search",
                "args": {"query": query},
                "reason": "High uncertainty, searching for more information"}

    # Default: try weather first
    return {"tool": "weather",
            "args": {"city": "paris"},
            "reason": "No context, starting with weather data"}


# ============================================================
# Decision logic
# ============================================================

def evaluate_result(tool_name: str, result: dict, step_count: int) -> tuple:
    """
    Evaluate tool result and decide next action.

    Returns (action, reason) where action is "continue" | "output" | "retry".
    """
    # ── Error → retry or fallback ──
    if result.get("error"):
        if step_count < 3:
            return ("retry", f"Tool {tool_name} failed: {result.get('message', 'unknown')}")
        return ("output", "Max retries exceeded after error")

    # ── Weather obtained → check if advice needed ──
    if tool_name == "weather" and not result.get("error"):
        if step_count >= 2:
            # Already got weather on a prior step — don't loop, output directly
            return ("output", "Weather already obtained, no further action")
        trace_decision("need_advice", value=True,
                       consumes={"weather_data": result},
                       true_branch="search_advice",
                       false_branch="output_directly")
        return ("continue", "Weather obtained, checking if advice needed")

    # ── Search done → decide if sufficient ──
    if tool_name == "search" and result.get("results"):
        advice = result["results"][0] if result["results"] else ""
        is_uncertain = "uncertain" in advice.lower() or "no specific" in advice.lower()
        trace_decision("advice_sufficient", value=not is_uncertain,
                       consumes={"search_result": advice},
                       true_branch="prepare_output",
                       false_branch="search_more")
        if is_uncertain and step_count < 4:
            return ("continue", "Advice uncertain, may need more data")
        return ("output", "Advice obtained")

    # ── Python executed → output ──
    if tool_name == "python":
        return ("output", "Calculation complete")

    # ── Memory op → continue or output ──
    if tool_name in ("memory_store", "memory_retrieve"):
        if step_count < 2:
            return ("continue", "Memory operation done, continuing")
        return ("output", "Memory operation complete")

    # ── Max steps guard ──
    if step_count >= 5:
        return ("output", "Max steps reached")

    return ("output", "Task complete")


# ============================================================
# Agent
# ============================================================

class AutonomousAgent:
    """
    Multi-tool autonomous agent with planning, routing, and memory.

    Execution loop:
        1. Classify intent
        2. Route to tool (deterministic → LLM fallback)
        3. Execute tool
        4. Evaluate result → decision (continue / output / retry)
        5. Store in memory
        6. Loop or return
    """

    def __init__(self, max_steps: int = 5):
        self.max_steps = max_steps
        self.memory: dict = {}
        self.history: list = []
        self.context: dict = {}

    def run(self, query: str) -> str:
        """Execute the agent for a given query. Returns final answer."""
        self.context = {}
        self.history = []

        # Step 0: Classify intent (LLM call)
        with trace_span("classify_intent", SEM.LLM,
                        inputs={"query": query}) as span:
            intent = self._classify(query)
            span["outputs"] = {"result": intent}
            span["produces"] = {"intent": intent}

        # Main loop
        final_answer = None
        for step_i in range(self.max_steps):
            # ── Route to tool ──
            tool_name, tool_args, routing_method, confidence = route_tool(
                query, self.context, self.history
            )

            trace_decision(
                f"route_to_{tool_name}",
                value=True,
                consumes={"intent": intent, "context": self.context},
                true_branch=f"execute_{tool_name}",
                false_branch="try_other_tool",
            )

            # ── Execute tool ──
            with trace_span(tool_name, SEM.TOOL,
                            inputs={"args": tool_args, "method": routing_method}) as span:
                result = self._execute_tool(tool_name, tool_args)
                span["outputs"] = {"result": result}
                span["produces"] = {f"{tool_name}_result": result}
                span["consumes"] = {"tool_args": tool_args}
            self.history.append({"tool": tool_name, "result": result, "step": step_i})

            # ── Update context ──
            if tool_name == "weather":
                self.context["weather_data"] = result
            elif tool_name == "search":
                self.context["search_result"] = result
            elif tool_name == "python":
                self.context["calc_result"] = result

            # ── Evaluate + decide ──
            action, reason = evaluate_result(tool_name, result, step_i + 1)
            self.context["last_action"] = action
            self.context["last_reason"] = reason

            if action == "output":
                final_answer = self._format_output(query, result, tool_name)
                break
            elif action == "retry":
                query = f"retry: {query}"  # Modify query for retry
                continue
            # "continue" → next loop iteration

        if final_answer is None:
            final_answer = self._format_fallback(query)

        # ── Store final result in memory ──
        with trace_span("memory_store", SEM.TOOL,
                        inputs={"key": "last_result", "value": final_answer}) as span:
            tool_memory_store("last_result", final_answer)
            span["outputs"] = {"result": "stored"}

        return final_answer

    def _classify(self, query: str) -> str:
        """Classify user intent."""
        q = query.lower()
        if any(w in q for w in ["weather", "temperature", "forecast"]):
            return "weather_inquiry"
        if any(w in q for w in ["calculate", "math", "+", "-", "*", "/"]):
            return "calculation"
        if any(w in q for w in ["advice", "should i", "good for", "recommend"]):
            return "advice_request"
        if any(w in q for w in ["recall", "remember"]):
            return "memory_recall"
        return "general_query"

    def _execute_tool(self, tool_name: str, args: dict) -> dict:
        """Execute a tool by name."""
        tools = {
            "weather":        lambda: tool_weather(**args),
            "search":         lambda: tool_search(**args),
            "python":         lambda: tool_python(**args),
            "memory_store":   lambda: tool_memory_store(**args),
            "memory_retrieve": lambda: tool_memory_retrieve(**args),
        }
        fn = tools.get(tool_name)
        if fn:
            return fn()
        return {"error": True, "message": f"Unknown tool: {tool_name}"}

    def _format_output(self, query: str, result: dict, tool_name: str) -> str:
        """Format the final answer."""
        if tool_name == "weather":
            w = result
            if w.get("error"):
                return f"Weather unavailable: {w.get('message')}"
            return (f"Weather in {w['city'].title()}: {w['temp']}C, {w['condition']}. "
                    f"Humidity: {w['humidity']}%, Wind: {w['wind']}km/h.")

        if tool_name == "search":
            r = result.get("results", [])
            advice = r[0] if r else "No advice found."
            return f"Advice: {advice}"

        if tool_name == "python":
            if result.get("error"):
                return f"Calculation error: {result.get('message')}"
            return f"Result: {result.get('result')}"

        if tool_name == "memory_retrieve":
            if result.get("found"):
                return f"Recalled: {result.get('value')}"
            return "Nothing found in memory."

        return str(result)

    def _format_fallback(self, query: str) -> str:
        """Fallback when max steps exceeded."""
        if self.context.get("weather_data"):
            w = self.context["weather_data"]
            return f"Weather: {w.get('temp', '?')}C, {w.get('condition', '?')}. Unable to provide full advice."
        return f"Unable to fully process: {query}"


# Convention: expose 'agent' variable for CLI
agent = AutonomousAgent()
