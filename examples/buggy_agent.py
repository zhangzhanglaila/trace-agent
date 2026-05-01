"""
Buggy Travel Agent — deliberately failure-prone demo workload for AgentTrace.

Failure modes (configurable):
  1. Non-deterministic LLM routing — router sometimes picks the wrong tool
  2. Memory staleness — cached weather from wrong city returns stale data
  3. Tool ambiguity — "weather_current" vs "weather_forecast" vs "climate_norms"
  4. Multi-hop failure — summarize step fails when upstream data is uncertain

The agent is a trip advisor:
  get_weather → search_activities → summarize → safety_check → recommend

Usage:
    # Case 1: "Why does Tokyo work but Paris doesn't?"
    python -m agent_obs.cli_main debug examples/buggy_agent.py \\
        -i "Trip to Tokyo for hiking" \\
        -j "Trip to Paris for hiking"

    # Case 2: "Why does the agent sometimes get stuck retrying?"
    python -m agent_obs.cli_main debug examples/buggy_agent.py \\
        -i "Trip to Sydney for surfing" \\
        -j "Trip to Mars for hiking"

    # Case 3: "Why was the wrong tool selected?"
    python -m agent_obs.cli_main debug examples/buggy_agent.py \\
        -i "What's the forecast for London? I want to go cycling" \\
        -j "What's the weather in London? I want to go cycling"
"""
import sys, os, json, re, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_obs.trace_core import trace_span, trace_decision, SEM, TracedAgent


# ============================================================
# Configuration — dial in failure rates here
# ============================================================
LLM_MISROUTE_RATE = 0.35    # chance LLM picks a similar-but-wrong tool
MEMORY_STALE_RATE = 0.40    # chance memory returns stale (wrong-city) data
SUMMARIZE_FAIL_RATE = 0.25  # chance summarize step produces uncertain output
SEED = 42                    # fixed seed for reproducibility (set None for true chaos)

# ============================================================
# Tool databases
# ============================================================

_WEATHER_DB = {
    "tokyo":    {"temp": 22, "condition": "sunny",  "humidity": 55, "wind": 8,  "forecast": "sunny, 24C"},
    "paris":    {"temp": 18, "condition": "cloudy", "humidity": 65, "wind": 12, "forecast": "rain likely, 15C"},
    "london":   {"temp": 12, "condition": "rainy",  "humidity": 80, "wind": 20, "forecast": "continued rain, 11C"},
    "sydney":   {"temp": 20, "condition": "clear",  "humidity": 60, "wind": 15, "forecast": "clear, 22C"},
    "new york": {"temp": 25, "condition": "sunny",  "humidity": 50, "wind": 10, "forecast": "partly cloudy, 23C"},
    "beijing":  {"temp": 30, "condition": "hazy",   "humidity": 45, "wind": 5,  "forecast": "haze warning, 28C"},
    "moscow":   {"temp": -5, "condition": "snow",   "humidity": 70, "wind": 25, "forecast": "heavy snow, -8C"},
    "mars":     None,  # triggers uncertainty
}

_CLIMATE_DB = {
    "tokyo":    "humid subtropical, mild winters, hot summers",
    "paris":    "temperate oceanic, cool winters, mild summers",
    "london":   "temperate maritime, frequent rain year-round",
    "sydney":   "humid subtropical, warm summers, mild winters",
    "new york": "humid continental, hot summers, cold winters",
    "beijing":  "continental monsoon, hot humid summers, cold dry winters",
    "moscow":   "humid continental, long cold winters, short warm summers",
}

_ACTIVITY_DB = {
    "hiking": {
        "sunny":       "Ideal hiking conditions. Trails dry and visible.",
        "cloudy":      "Acceptable for hiking. Watch for changing conditions.",
        "rainy":       "Hiking not advised. Trails will be slippery and dangerous.",
        "clear":       "Excellent hiking weather. Full visibility on trails.",
        "hazy":        "Hiking possible but views limited. Check air quality.",
        "snow":        "Winter hiking only with proper gear. Avalanche risk.",
    },
    "cycling": {
        "sunny":       "Great cycling weather. Stay hydrated.",
        "cloudy":      "Good for cycling. Light jacket recommended.",
        "rainy":       "Cycling dangerous. Roads slippery, visibility low.",
        "clear":       "Perfect cycling weather. Enjoy the ride.",
        "hazy":        "Not recommended for cycling. Air quality concern.",
        "snow":        "Cycling not possible. Icy roads.",
    },
    "surfing": {
        "sunny":       "Good surfing. Waves moderate, water warm.",
        "cloudy":      "Surfable conditions. Check tide charts.",
        "rainy":       "Surfing possible but watch for rip currents.",
        "clear":       "Excellent surfing. Clean swell.",
        "hazy":        "Surfing OK but check water quality advisory.",
        "snow":        "Cold water surfing only with wetsuit.",
    },
}

_SAFETY_DB = {
    "sunny":  "No safety concerns. Normal precautions.",
    "cloudy": "Monitor weather for sudden changes.",
    "rainy":  "Exercise caution. Slippery surfaces, reduced visibility.",
    "clear":  "No safety concerns. Ideal conditions.",
    "hazy":   "Air quality advisory. Limit outdoor exposure.",
    "snow":   "Hazardous conditions. Not recommended without proper gear.",
}


# ============================================================
# Tool implementations — deliberately overlapping names
# ============================================================

def tool_weather_current(city: str) -> dict:
    """Get current weather for a city."""
    city_key = city.lower().strip()
    data = _WEATHER_DB.get(city_key)
    if data is None:
        return {"tool": "weather_current", "city": city, "error": True,
                "message": f"No weather data for {city}", "uncertainty": "high"}
    return {"tool": "weather_current", "city": city, "error": False, **data}


def tool_weather_forecast(city: str) -> dict:
    """Get weather forecast for a city."""
    city_key = city.lower().strip()
    data = _WEATHER_DB.get(city_key)
    if data is None:
        return {"tool": "weather_forecast", "city": city, "error": True,
                "message": f"No forecast for {city}"}
    return {"tool": "weather_forecast", "city": city, "forecast": data["forecast"],
            "error": False}


def tool_climate_norms(city: str) -> dict:
    """Get typical climate for a city (not current weather)."""
    city_key = city.lower().strip()
    climate = _CLIMATE_DB.get(city_key)
    if climate is None:
        return {"tool": "climate_norms", "city": city, "error": True,
                "message": f"No climate data for {city}"}
    return {"tool": "climate_norms", "city": city, "climate": climate, "error": False}


def tool_activity_search(activity: str, condition: str = None) -> dict:
    """Search for activity advice given weather condition."""
    act = activity.lower().strip()
    kb = _ACTIVITY_DB.get(act)
    if not kb:
        return {"tool": "activity_search", "activity": activity, "error": True,
                "message": f"Unknown activity: {activity}"}
    cond = (condition or "sunny").lower().strip()
    advice = kb.get(cond, f"No specific {act} advice for {cond}.")
    return {"tool": "activity_search", "activity": activity, "condition": cond,
            "advice": advice, "error": False}


def tool_safety_check(condition: str) -> dict:
    """Check safety conditions for outdoor activity."""
    cond = condition.lower().strip()
    warning = _SAFETY_DB.get(cond, "Unknown conditions — exercise caution.")
    risk = "high" if cond in ("rainy", "snow", "hazy") else "low"
    return {"tool": "safety_check", "condition": cond, "warning": warning,
            "risk_level": risk, "error": False}


def tool_summarize(findings: dict = None, **kwargs) -> dict:
    """Summarize multi-step findings into a coherent recommendation."""
    # Handle misrouted args: if we get activity_search type args, wrap them
    if findings is None:
        if kwargs:
            findings = kwargs
        else:
            return {"tool": "summarize", "error": True,
                    "message": "No findings provided to summarize"}
    # Deliberately fragile: fails when uncertainty is high
    if findings.get("uncertainty") == "high":
        return {"tool": "summarize", "error": True,
                "message": "Cannot summarize: too much uncertainty in source data"}
    if findings.get("error"):
        return {"tool": "summarize", "error": True,
                "message": "Cannot summarize: upstream data error"}
    # Simulate occasional failure even with valid data
    if random.random() < SUMMARIZE_FAIL_RATE:
        return {"tool": "summarize", "error": True,
                "message": "Summarization failed: model confidence too low"}
    return {"tool": "summarize", "summary": str(findings)[:200], "error": False}


# Buggy memory — can return stale data from wrong city
_MEMORY: dict = {}

def tool_memory_store(key: str, value: any) -> dict:
    """Store value in memory."""
    _MEMORY[key] = value
    return {"stored": True, "key": key}

def tool_memory_retrieve(key: str) -> dict:
    """Retrieve from memory — sometimes returns stale data."""
    if random.random() < MEMORY_STALE_RATE and key in _MEMORY:
        # Return a different key's value (simulating stale cache)
        other_keys = [k for k in _MEMORY if k != key]
        if other_keys:
            stale_key = random.choice(other_keys)
            return {"found": True, "key": stale_key, "value": _MEMORY[stale_key],
                    "stale": True, "requested_key": key}
    if key in _MEMORY:
        return {"found": True, "key": key, "value": _MEMORY[key], "stale": False}
    return {"found": False, "key": key}


# ============================================================
# Tool Registry — note the deliberate ambiguity
# ============================================================

TOOLS = {
    "weather_current":  tool_weather_current,
    "weather_forecast": tool_weather_forecast,
    "climate_norms":    tool_climate_norms,
    "activity_search":  tool_activity_search,
    "safety_check":     tool_safety_check,
    "summarize":        tool_summarize,
    "memory_store":     tool_memory_store,
    "memory_retrieve":  tool_memory_retrieve,
}

# Tool aliases that the LLM can confuse
AMBIGUOUS_ALIASES = {
    "weather_current":   ["weather_forecast", "climate_norms"],
    "weather_forecast":  ["weather_current", "climate_norms"],
    "climate_norms":     ["weather_current", "weather_forecast"],
    "activity_search":    ["safety_check", "summarize"],
    "safety_check":       ["activity_search"],
    "summarize":          ["activity_search"],
}


# ============================================================
# Buggy LLM Router — non-deterministic, makes mistakes
# ============================================================

def _llm_plan(query: str, context: dict, history: list, step_index: int = -1,
              misroute_on_steps: set = None, misroute_to: str = None) -> dict:
    """
    Simulated LLM planner that SOMETIMES picks the wrong tool.

    Deterministic baseline + non-deterministic errors injected at LLM_MISROUTE_RATE.
    If misroute_on_steps is provided, only misroutes on those specific step indices.
    If misroute_to is provided, forces misroute to that specific tool.
    """
    q = query.lower()

    with trace_span("planner_llm", SEM.LLM,
                    inputs={"query": query, "context_keys": list(context.keys())[:5]}) as span:

        # ── Deterministic baseline ──
        plan = _deterministic_plan(q, context)

        # ── Inject non-determinism ──
        should_misroute = random.random() < LLM_MISROUTE_RATE
        if misroute_on_steps is not None:
            should_misroute = step_index in misroute_on_steps

        if should_misroute:
            original_tool = plan["tool"]
            if misroute_to:
                plan["tool"] = misroute_to
            else:
                candidates = AMBIGUOUS_ALIASES.get(original_tool, [])
                if candidates:
                    plan["tool"] = random.choice(candidates)
            plan["reason"] = f"LLM hallucinated: chose {plan['tool']} instead of {original_tool}"
            plan["misrouted"] = True

        span["outputs"] = {"result": json.dumps(plan)}
        span["produces"] = {"plan": plan, "selected_tool": plan["tool"]}
        span["misrouted"] = plan.get("misrouted", False)
        return plan


def _deterministic_plan(q: str, context: dict) -> dict:
    """The 'correct' plan — before LLM hallucination injects errors."""

    # ── CONTEXT-DRIVEN RULES (check state first, not keywords) ──

    # Got weather + activity + safety → summarize everything
    if context and "weather_data" in context and "activity_result" in context:
        if "safety_result" in context:
            return {"tool": "summarize",
                    "args": {"findings": {"weather": context["weather_data"],
                                         "activity": context["activity_result"],
                                         "safety": context["safety_result"]}},
                    "reason": "All data collected, summarizing final recommendation"}
        return {"tool": "summarize",
                "args": {"findings": {"weather": context["weather_data"],
                                     "activity": context["activity_result"]}},
                "reason": "Weather and activity available, summarizing"}

    # Got weather + safety → now search activity
    if context and "weather_data" in context and "safety_result" in context \
       and "activity_result" not in context:
        wd = context["weather_data"]
        if not wd.get("error"):
            activity = _extract_activity(q)
            cond = wd.get("condition", "sunny")
            return {"tool": "activity_search",
                    "args": {"activity": activity, "condition": cond},
                    "reason": f"Weather + safety done, searching {activity} advice"}

    # Got weather + risky condition → safety check next
    if context and "weather_data" in context and "activity_result" not in context \
       and "safety_result" not in context:
        wd = context["weather_data"]
        if not wd.get("error"):
            activity = _extract_activity(q)
            cond = wd.get("condition", "sunny")
            # If condition looks risky, safety check first
            if cond in ("rainy", "snow", "hazy"):
                return {"tool": "safety_check", "args": {"condition": cond},
                        "reason": f"Risky condition ({cond}), checking safety before activity"}
            return {"tool": "activity_search",
                    "args": {"activity": activity, "condition": cond},
                    "reason": f"Weather available ({cond}), searching {activity} advice"}

    # Got activity but no weather → get weather (unless query specifically avoids it)
    if context and "activity_result" in context and "weather_data" not in context:
        city = _extract_city(q)
        return {"tool": "weather_current", "args": {"city": city},
                "reason": "Need weather context for activity advice"}

    # ── QUERY-DRIVEN RULES (only when context is empty) ──

    if "forecast" in q:
        city = _extract_city(q)
        return {"tool": "weather_forecast", "args": {"city": city},
                "reason": f"Forecast requested for {city}"}

    if "climate" in q:
        city = _extract_city(q)
        return {"tool": "climate_norms", "args": {"city": city},
                "reason": f"Climate data requested for {city}"}

    if any(w in q for w in ["weather", "temperature", "how hot", "how cold"]):
        city = _extract_city(q)
        return {"tool": "weather_current", "args": {"city": city},
                "reason": f"Weather requested for {city}"}

    if "safe" in q or "safety" in q:
        cond = context.get("weather_data", {}).get("condition", "sunny")
        return {"tool": "safety_check", "args": {"condition": cond},
                "reason": "Safety check requested"}

    # ── Default: get weather first ──
    city = _extract_city(q)
    return {"tool": "weather_current", "args": {"city": city},
            "reason": "No context available, starting with weather"}


def _extract_city(q: str) -> str:
    for city in _WEATHER_DB:
        if city in q:
            return city
    return "london"  # default

def _extract_activity(q: str) -> str:
    for act in _ACTIVITY_DB:
        if act in q:
            return act
    return "hiking"


# ============================================================
# Decision logic — evaluates results, triggers retries
# ============================================================

def evaluate_step(tool_name: str, result: dict, context: dict, step_count: int) -> tuple:
    """
    Evaluate tool result and decide next action.

    Returns (action, reason) where action is "continue" | "output" | "retry".
    """
    # ── Error handling → retry ──
    if result.get("error"):
        if step_count < 3:
            return ("retry", f"{tool_name} failed: {result.get('message','?')}")
        return ("output", f"Max retries after {tool_name} failure")

    # ── Weather obtained → continue to search ──
    if tool_name in ("weather_current", "weather_forecast", "climate_norms"):
        trace_decision("need_activity_search", value=True,
                       consumes={"weather_data": result},
                       true_branch="search_activity",
                       false_branch="output_weather_only")
        return ("continue", f"{tool_name} done, searching activities next")

    # ── Activity search done → check safety ──
    if tool_name == "activity_search":
        risk_activities = ["rainy", "snow", "hazy"]
        cond = result.get("condition", "")
        needs_safety = any(r in cond for r in risk_activities)
        trace_decision("needs_safety_check", value=needs_safety,
                       consumes={"activity_result": result},
                       true_branch="check_safety",
                       false_branch="summarize_directly")
        if needs_safety:
            return ("continue", "Risky conditions, checking safety next")
        return ("output", "Activity advice obtained")

    # ── Safety check done → summarize ──
    if tool_name == "safety_check":
        trace_decision("risk_is_acceptable", value=result.get("risk_level") == "low",
                       consumes={"safety_result": result},
                       true_branch="summarize",
                       false_branch="output_with_warning")
        return ("continue", "Safety checked, summarizing")

    # ── Summarize done → output ──
    if tool_name == "summarize":
        return ("output", "Summary complete")

    # ── Memory ops → continue ──
    if tool_name in ("memory_store", "memory_retrieve"):
        if step_count < 2:
            return ("continue", "Memory op done")
        return ("output", "Task complete")

    if step_count >= 7:
        return ("output", "Max steps reached")

    return ("output", "Task complete")


# ============================================================
# BuggyAgent
# ============================================================

class BuggyAgent:
    """
    Deliberately failure-prone travel advisor agent.

    Failure modes:
      - LLM_MISROUTE_RATE: Router picks wrong tool (e.g., climate instead of weather)
      - MEMORY_STALE_RATE: Memory returns data from wrong city
      - SUMMARIZE_FAIL_RATE: Summarization fails on valid input

    The causal debugger should diagnose WHY failures happened, not just that they did.
    """

    def __init__(self, max_steps: int = 7, seed: int = SEED,
                 misroute_on_steps: set = None, misroute_to: str = None):
        self.max_steps = max_steps
        self.context: dict = {}
        self.history: list = []
        self.misroute_on_steps = misroute_on_steps  # None = use random, set = exact steps
        self.misroute_to = misroute_to              # Force misroute to specific tool
        if seed is not None:
            random.seed(seed)

    def run(self, query: str) -> str:
        self.context = {}
        self.history = []

        # Step 0: Classify intent
        with trace_span("classify_intent", SEM.LLM,
                        inputs={"query": query}) as span:
            intent = self._classify(query)
            span["outputs"] = {"result": intent}
            span["produces"] = {"intent": intent}

        # Main loop
        final_answer = None
        for step_i in range(self.max_steps):
            # ── Plan next tool (LLM with possible hallucination) ──
            plan = _llm_plan(query, self.context, self.history,
                           step_index=step_i,
                           misroute_on_steps=self.misroute_on_steps,
                           misroute_to=self.misroute_to)
            tool_name = plan["tool"]
            tool_args = plan.get("args", {})

            trace_decision(
                f"route_to_{tool_name}",
                value=True,
                consumes={"intent": intent, "context_keys": sorted(self.context.keys())},
                true_branch=f"execute_{tool_name}",
                false_branch="try_other_tool",
            )

            # ── Execute tool ──
            with trace_span(tool_name, SEM.TOOL,
                            inputs={"args": tool_args, "misrouted": plan.get("misrouted", False)}) as span:
                result = self._execute(tool_name, tool_args)
                span["outputs"] = {"result": result}
                span["produces"] = {f"{tool_name}_result": result}
                span["consumes"] = {"tool_args": tool_args}
                if plan.get("misrouted"):
                    span["misrouted"] = True

            self.history.append({"tool": tool_name, "result": result, "step": step_i})

            # ── Update context ──
            if tool_name == "weather_current":
                self.context["weather_data"] = result
            elif tool_name == "weather_forecast":
                self.context["weather_data"] = result  # overlaps with weather_current!
            elif tool_name == "climate_norms":
                self.context["climate_data"] = result
            elif tool_name == "activity_search":
                self.context["activity_result"] = result
            elif tool_name == "safety_check":
                self.context["safety_result"] = result
            elif tool_name == "summarize":
                self.context["summary"] = result

            # ── Evaluate + decide ──
            action, reason = evaluate_step(tool_name, result, self.context, step_i + 1)
            self.context["last_action"] = action
            self.context["last_reason"] = reason

            if action == "output":
                final_answer = self._format_output(result, tool_name)
                break
            elif action == "retry":
                query = f"retry: {query}"
                continue

        if final_answer is None:
            final_answer = self._format_fallback()

        return final_answer

    def _classify(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["trip", "travel", "visit"]):
            return "trip_planning"
        if "forecast" in q:
            return "forecast_request"
        if any(w in q for w in ["weather", "temperature"]):
            return "weather_inquiry"
        if "safe" in q:
            return "safety_check"
        return "general_query"

    def _execute(self, tool_name: str, args: dict) -> dict:
        fn = TOOLS.get(tool_name)
        if fn:
            try:
                return fn(**args)
            except TypeError as e:
                return {"error": True,
                        "message": f"Tool {tool_name} arg mismatch: {e}",
                        "wrong_args": list(args.keys()),
                        "misrouted": True}
        return {"error": True, "message": f"Unknown tool: {tool_name}"}

    def _format_output(self, result: dict, tool_name: str) -> str:
        if tool_name == "weather_current":
            w = result
            if w.get("error"):
                return f"[FAIL] Weather unavailable: {w.get('message')}"
            return (f"[OK] Weather in {w['city'].title()}: {w['temp']}C, {w['condition']}. "
                    f"Humidity: {w['humidity']}%, Wind: {w['wind']}km/h.")

        if tool_name == "weather_forecast":
            if result.get("error"):
                return f"[FAIL] Forecast unavailable: {result.get('message')}"
            return f"[OK] Forecast for {result['city'].title()}: {result['forecast']}."

        if tool_name == "climate_norms":
            if result.get("error"):
                return f"[FAIL] Climate data unavailable."
            return f"[INFO] Climate: {result['climate']}."

        if tool_name == "activity_search":
            return f"[OK] Activity advice: {result.get('advice', 'No advice')}"

        if tool_name == "safety_check":
            risk = result.get("risk_level", "unknown")
            return f"[{'WARN' if risk == 'high' else 'OK'}] Safety ({risk} risk): {result.get('warning')}"

        if tool_name == "summarize":
            if result.get("error"):
                return f"[FAIL] Summarization failed: {result.get('message')}"
            return f"[OK] Summary: {result.get('summary', '')}"

        return str(result)

    def _format_fallback(self) -> str:
        parts = []
        if "weather_data" in self.context:
            w = self.context["weather_data"]
            parts.append(f"Weather: {w.get('temp','?')}C, {w.get('condition','?')}")
        if "activity_result" in self.context:
            a = self.context["activity_result"]
            parts.append(f"Activity: {a.get('advice','?')}")
        if "safety_result" in self.context:
            s = self.context["safety_result"]
            parts.append(f"Safety: {s.get('risk_level','?')} risk")
        if parts:
            return "[PARTIAL] " + " | ".join(parts)
        return f"[FAIL] Unable to process request"


agent = BuggyAgent()
