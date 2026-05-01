"""
Travel Planner Agent — a realistic multi-tool agent for trip planning.

Tools: weather_current, activity_search, safety_check, summarize, memory_store, memory_retrieve
Pipeline: classify → plan → weather → plan → activity → safety → summarize → output

The Bug: LLM planner sometimes selects `summarize` instead of `activity_search`
after getting weather data — a subtle tool selection error that causes
incomplete travel plans and cascading retries.

Usage:
    python examples/travel_planner.py              # Run demo with bug
    python examples/travel_planner.py --correct    # Run without bug (baseline)
    python examples/travel_planner.py --tokyo      # Tokyo trip (works)
    python examples/travel_planner.py --paris       # Paris trip (triggers bug)
"""
import sys, os, json, re, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_obs.trace_core import trace_span, trace_decision, SEM, TracedAgent

# ============================================================
# Knowledge Base
# ============================================================

WEATHER_DB = {
    "tokyo":     {"city": "Tokyo",     "temp": 22, "condition": "sunny",  "humidity": 55, "wind_kmh": 8,  "season": "spring"},
    "paris":     {"city": "Paris",     "temp": 14, "condition": "cloudy", "humidity": 68, "wind_kmh": 15, "season": "spring"},
    "london":    {"city": "London",    "temp": 10, "condition": "rainy",  "humidity": 82, "wind_kmh": 22, "season": "spring"},
    "sydney":    {"city": "Sydney",    "temp": 24, "condition": "clear",  "humidity": 50, "wind_kmh": 12, "season": "autumn"},
    "new york":  {"city": "New York",  "temp": 18, "condition": "sunny",  "humidity": 45, "wind_kmh": 10, "season": "spring"},
    "bangkok":   {"city": "Bangkok",   "temp": 34, "condition": "hot",    "humidity": 75, "wind_kmh": 5,  "season": "summer"},
    "reykjavik": {"city": "Reykjavik", "temp": 3,  "condition": "cold",   "humidity": 70, "wind_kmh": 30, "season": "winter"},
    "mars":      None,  # No data — triggers error path
}

ACTIVITY_DB = {
    "hiking": {
        "sunny 22C":  "Excellent hiking weather. Trails are dry and visible. Recommended route: Mount Takao (3h).",
        "cloudy 14C": "Decent hiking conditions. Trails may be damp. Recommended route: Montmartre stairs walk (1.5h).",
        "rainy 10C":  "Poor hiking conditions. Trails are slippery and dangerous. Consider indoor alternatives.",
        "clear 24C":  "Perfect hiking weather. Recommended: Blue Mountains trail (4h).",
        "sunny 18C":  "Great hiking conditions. Recommended: Hudson Valley day hike (5h).",
        "hot 34C":    "Too hot for hiking. Risk of heat exhaustion. Not recommended.",
        "cold 3C":    "Hiking not advised. Risk of hypothermia. Recommend indoor activities only.",
    },
    "cycling": {
        "sunny 22C":  "Great cycling weather. Recommended: Shimanami Kaido route (day trip).",
        "cloudy 14C": "Acceptable cycling. Watch for wet roads. Recommended: Seine river path (2h).",
        "rainy 10C":  "Cycling not recommended. Roads are slippery and visibility is poor.",
        "clear 24C":  "Ideal cycling conditions. Recommended: Coastal route to Bondi (3h).",
        "sunny 18C":  "Good cycling weather. Recommended: Central Park loop (1.5h).",
        "hot 34C":    "Cycling is dangerous in this heat. Not recommended.",
        "cold 3C":    "Cycling not advised due to icy roads and strong winds.",
    },
    "sightseeing": {
        "sunny 22C":  "Perfect for sightseeing. Visit Senso-ji Temple, Meiji Shrine, and Shibuya Crossing.",
        "cloudy 14C": "Good for museums and indoor attractions. Louvre, Musee d'Orsay recommended.",
        "rainy 10C":  "Best for indoor sightseeing. British Museum, Tate Modern, National Gallery.",
        "clear 24C":  "Excellent for outdoor sightseeing. Opera House, Harbour Bridge walk.",
        "sunny 18C":  "Great sightseeing weather. Statue of Liberty, Times Square, Central Park.",
        "hot 34C":    "Outdoor sightseeing is uncomfortable. Visit air-conditioned malls and temples.",
        "cold 3C":    "Limited outdoor sightseeing. Northern Lights tour available (weather permitting).",
    },
    "food": {
        "sunny 22C":  "Explore Tsukiji Outer Market for fresh sushi and street food.",
        "cloudy 14C": "Perfect day for Parisian cafes and patisseries. Try Le Marais district.",
        "rainy 10C":  "Cozy pub lunch recommended. Try Borough Market for indoor food hall.",
        "clear 24C":  "Outdoor dining at The Rocks markets. Fresh seafood recommended.",
        "sunny 18C":  "Food truck festival weather. Try Smorgasburg in Brooklyn.",
        "hot 34C":    "Street food is best enjoyed early morning or evening. Try night markets.",
        "cold 3C":    "Warm soup and hot chocolate tour. Indoor food halls recommended.",
    },
}

SAFETY_DB = {
    "hiking": {
        "sunny":  "Safe. Bring water and sunscreen.",
        "cloudy": "Safe. Bring rain jacket as precaution.",
        "rainy":  "CAUTION: slippery trails. Hiking boots required.",
        "clear":  "Safe. Standard precautions apply.",
        "hot":    "WARNING: high heat. Hike early morning only. Bring 2L water minimum.",
        "cold":   "DANGER: risk of hypothermia. Proper winter gear required.",
    },
    "cycling": {
        "sunny":  "Safe. Wear helmet and bring water.",
        "cloudy": "Safe. Use lights and wear reflective gear.",
        "rainy":  "CAUTION: reduced visibility and braking. Not recommended for casual riders.",
        "clear":  "Safe. Standard road rules apply.",
        "hot":    "WARNING: heat stroke risk. Cycle early morning. Bring extra water.",
        "cold":   "DANGER: ice patches possible. Not recommended without studded tires.",
    },
}


# ============================================================
# Tool implementations
# ============================================================

def tool_weather(city: str) -> dict:
    """Get current weather for a destination city."""
    city_key = city.lower().strip()
    data = WEATHER_DB.get(city_key)
    if data is None:
        return {"city": city, "error": True, "message": f"No weather data for {city}"}
    return {"city": data["city"], "error": False, **{k: v for k, v in data.items() if k != "city"}}


def tool_activity_search(activity: str, condition: str, temp: int) -> dict:
    """Search for activity recommendations based on weather conditions."""
    act_key = activity.lower().strip()
    weather_key = f"{condition} {temp}C"

    act_db = ACTIVITY_DB.get(act_key, {})
    advice = act_db.get(weather_key)

    if not advice:
        # Fuzzy match by condition
        for key, val in act_db.items():
            if condition in key.lower():
                advice = val
                break

    if not advice:
        advice = f"No specific {activity} recommendations for {weather_key}. Check local guides."

    return {
        "activity": activity,
        "condition": condition,
        "temp": temp,
        "recommendation": advice,
        "found": advice is not None,
    }


def tool_safety_check(activity: str, condition: str) -> dict:
    """Check safety conditions for a given activity and weather."""
    act_key = activity.lower().strip()
    cond_key = condition.lower().strip()

    act_safety = SAFETY_DB.get(act_key, {})
    warning = act_safety.get(cond_key, "No specific safety data. Exercise normal caution.")

    is_danger = warning.startswith("DANGER") or warning.startswith("WARNING")

    return {
        "activity": activity,
        "condition": condition,
        "warning": warning,
        "safe": not is_danger,
        "level": "danger" if "DANGER" in warning else ("caution" if "CAUTION" in warning or "WARNING" in warning else "safe"),
    }


def tool_summarize(plan: dict) -> dict:
    """Summarize the travel plan into a human-readable output."""
    if not plan or not isinstance(plan, dict):
        return {"error": True, "message": "Cannot summarize: plan is empty or invalid"}

    # If plan is missing critical sections, fail — this is what makes the bug visible
    if not plan.get("activities") and not plan.get("error"):
        return {"error": True,
                "message": "Summarization failed: plan is incomplete (missing activity recommendations). "
                           "The LLM attempted to summarize before collecting all data.",
                "missing": "activities"}

    city = plan.get("city", "Unknown")
    weather = plan.get("weather", {})
    activities = plan.get("activities", [])
    safety = plan.get("safety", {})

    parts = [f"Travel Plan for {city}"]

    if weather and not weather.get("error"):
        parts.append(f"Weather: {weather.get('temp')}C, {weather.get('condition')}")

    if activities:
        parts.append("Activities:")
        for act in activities:
            parts.append(f"  - {act.get('activity', '?')}: {act.get('recommendation', '')[:120]}")

    if safety:
        parts.append(f"Safety: {safety.get('warning', 'No safety concerns.')}")

    summary = "\n".join(parts)
    return {"summary": summary, "plan": plan, "error": False}


# In-memory storage
_MEMORY: dict = {}


def tool_memory_store(key: str, value: any) -> dict:
    """Store a value in agent memory."""
    _MEMORY[key] = value
    return {"stored": True, "key": key}


def tool_memory_retrieve(key: str) -> dict:
    """Retrieve a value from agent memory."""
    if key in _MEMORY:
        return {"found": True, "key": key, "value": _MEMORY[key]}
    for k, v in _MEMORY.items():
        if key in k or k in key:
            return {"found": True, "key": k, "value": v, "partial_match": True}
    return {"found": False, "key": key}


# ============================================================
# LLM Planner (with the bug)
# ============================================================

# Bug configuration — can be toggled
LLM_MISROUTE_ENABLED = True   # When True, the bug is active
LLM_MISROUTE_STEP = 1         # Step index where bug triggers (after weather, before activity)
LLM_MISROUTE_TO = "summarize"  # Wrong tool to route to


def llm_plan(query: str, context: dict, step_index: int) -> dict:
    """
    LLM-based tool planning. This is where the bug lives.

    Bug: At step LLM_MISROUTE_STEP, if misroute is enabled and context has
    weather data but no activity data, the LLM incorrectly selects `summarize`
    instead of `activity_search`. This is a subtle, realistic bug — the LLM
    "sees" weather data and decides to summarize the plan prematurely,
    skipping the activity search step entirely.
    """
    q = query.lower()

    with trace_span("planner_llm", SEM.LLM,
                    inputs={"query": query, "context": str(context)[:200],
                            "step": step_index}) as span:

        # ── THE BUG ──
        # Triggers at step LLM_MISROUTE_STEP AND on retry steps (3, 4) when the
        # first misroute failed — creating a realistic error cascade.
        is_retry = "retry" in q
        bug_step = step_index == LLM_MISROUTE_STEP or (is_retry and step_index in (2, 3))

        if (LLM_MISROUTE_ENABLED
                and bug_step
                and context
                and "weather_data" in context
                and "activity_data" not in context):

            # BUG: LLM incorrectly routes to summarize instead of activity_search.
            # This is a realistic LLM failure mode: the model confuses "having
            # weather data" with "having a complete plan" and tries to summarize
            # prematurely. On retry, it repeats the same mistake because the
            # context still shows weather data but no activity plan.
            wd = context["weather_data"]
            if not wd.get("error"):
                plan = {
                    "tool": LLM_MISROUTE_TO,
                    "args": {"plan": {"weather": wd}},
                    "reason": "Have weather data, ready to summarize plan" if not is_retry
                              else "Retry: still see weather data, attempting to summarize again",
                    "_bug": True,
                    "_correct_tool": "activity_search",
                    "_bug_reason": ("LLM hallucinated plan completeness from weather data alone"
                                   if not is_retry else
                                   "LLM repeated same misroute on retry — context unchanged, "
                                   "deterministic failure pattern"),
                }
                activity = _extract_activity(q)
                plan["_would_have_routed_to"] = {
                    "tool": "activity_search",
                    "args": {"activity": activity, "condition": wd.get("condition", "sunny"),
                             "temp": wd.get("temp", 20)},
                }

                span["outputs"] = {"result": json.dumps(plan)}
                span["produces"] = {"plan": plan}
                return plan

        # ── Normal LLM planning (when bug doesn't trigger) ──
        plan = _normal_plan(q, context, step_index)
        span["outputs"] = {"result": json.dumps(plan)}
        span["produces"] = {"plan": plan}
        return plan


def _normal_plan(query: str, context: dict, step_index: int) -> dict:
    """Normal (correct) LLM planning logic. Conditions ordered most→least specific."""
    q = query.lower()

    wd = context.get("weather_data", {})

    # Step 0: No weather → get weather first
    if not wd:
        city = _extract_city(q)
        return {"tool": "weather_current",
                "args": {"city": city},
                "reason": f"No weather data yet, fetching weather for {city}"}

    # Weather error → can't proceed, summarize failure
    if wd.get("error"):
        return {"tool": "summarize",
                "args": {"plan": {"city": wd.get("city", "unknown"), "weather": wd,
                                  "activities": [], "error": "No weather data available"}},
                "reason": "Weather unavailable, summarizing with error"}

    # Have safety → summarize the full plan (MOST specific — check first)
    if context.get("safety_data"):
        city = wd.get("city", _extract_city(q))
        plan = {
            "city": city,
            "weather": wd,
            "activities": [context.get("activity_data", {})],
            "safety": context.get("safety_data", {}),
        }
        return {"tool": "summarize",
                "args": {"plan": plan},
                "reason": "All data collected (weather + activity + safety), summarizing travel plan"}

    # Have weather + activity → check safety next
    if context.get("activity_data"):
        ad = context.get("activity_data", {})
        activity = ad.get("activity", _extract_activity(q))
        return {"tool": "safety_check",
                "args": {"activity": activity,
                         "condition": wd.get("condition", "sunny")},
                "reason": f"Weather + activity done, checking safety for {activity}"}

    # Have weather only → search for activities
    activity = _extract_activity(q)
    return {"tool": "activity_search",
            "args": {"activity": activity,
                     "condition": wd.get("condition", "sunny"),
                     "temp": wd.get("temp", 20)},
            "reason": f"Weather obtained ({wd.get('condition')}, {wd.get('temp')}C), searching {activity} activities"}


def _extract_city(query: str) -> str:
    """Extract city name from query."""
    for city in WEATHER_DB:
        if city in query.lower():
            return city
    return "paris"  # default


def _extract_activity(query: str) -> str:
    """Extract activity type from query."""
    for act in ["hiking", "cycling", "sightseeing", "food", "running", "walking", "surfing"]:
        if act in query.lower():
            return act
    return "sightseeing"  # default


# ============================================================
# Travel Planner Agent
# ============================================================

class TravelPlanner:
    """
    Multi-step travel planning agent with tool chaining.

    Pipeline: classify → [plan → tool] × N → output

    The agent follows a natural planning loop:
    1. Classify user intent
    2. Plan next tool call
    3. Execute tool
    4. Update context
    5. Decide whether to continue or output
    """

    def __init__(self, max_steps: int = 8, enable_bug: bool = True):
        self.max_steps = max_steps
        self.enable_bug = enable_bug
        self.context: dict = {}
        self.history: list = []

    def run(self, query: str) -> str:
        """Execute the travel planning pipeline."""
        global LLM_MISROUTE_ENABLED
        LLM_MISROUTE_ENABLED = self.enable_bug

        self.context = {}
        self.history = []

        # Step 0: Classify intent
        with trace_span("classify_intent", SEM.LLM,
                        inputs={"query": query}) as span:
            intent = self._classify(query)
            span["outputs"] = {"result": intent}
            span["produces"] = {"intent": intent}

        # Main planning loop
        final_answer = None
        for step_i in range(self.max_steps):
            # ── Plan ──
            plan = llm_plan(query, self.context, step_i)
            tool_name = plan["tool"]
            tool_args = plan["args"]

            trace_decision(
                f"route_to_{tool_name}",
                value=True,
                consumes={"context": self.context, "plan": plan},
                true_branch=f"execute_{tool_name}",
                false_branch="try_alternative",
            )

            # ── Execute tool ──
            with trace_span(tool_name, SEM.TOOL,
                            inputs={"args": tool_args, "plan_reason": plan.get("reason", "")}) as span:
                result = self._execute(tool_name, tool_args)
                span["outputs"] = {"result": result}
                span["produces"] = {f"{tool_name}_result": result}
                span["consumes"] = {"tool_args": tool_args}

                # If this was a bug misroute, record the counterfactual
                if plan.get("_bug"):
                    span["_bug"] = True
                    span["_correct_tool"] = plan.get("_correct_tool")
                    span["_bug_reason"] = plan.get("_bug_reason")
                    span["_would_have_routed_to"] = plan.get("_would_have_routed_to")

            self.history.append({"step": step_i, "tool": tool_name, "result": result})

            # ── Update context ──
            if tool_name == "weather_current":
                self.context["weather_data"] = result
            elif tool_name == "activity_search":
                self.context["activity_data"] = result
            elif tool_name == "safety_check":
                self.context["safety_data"] = result
            elif tool_name == "summarize":
                self.context["summary_data"] = result

            # ── Decide next action ──
            action = self._decide(tool_name, result, step_i)

            if action == "output":
                if tool_name == "summarize" and not result.get("error"):
                    final_answer = result.get("summary", str(result))
                elif tool_name == "weather_current" and result.get("error"):
                    final_answer = f"[FAIL] {result.get('message', 'Weather unavailable')}"
                elif tool_name == "summarize" and result.get("error"):
                    final_answer = f"[FAIL] {result.get('message', 'Plan summarization failed')}"
                elif tool_name == "activity_search":
                    final_answer = f"[OK] Activity advice: {result.get('recommendation', '')[:200]}"
                else:
                    final_answer = f"[OK] {str(result)[:200]}"
                break
            elif action == "retry":
                query = f"retry: {query}"
                continue

        if final_answer is None:
            final_answer = f"[PARTIAL] Planning incomplete. Context: {str(self.context)[:200]}"

        # Store in memory
        with trace_span("memory_store", SEM.TOOL,
                        inputs={"key": "last_plan", "value": final_answer}) as span:
            tool_memory_store("last_plan", final_answer)
            span["outputs"] = {"result": "stored"}

        return final_answer

    def _classify(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["trip", "travel", "plan", "visit", "go to", "vacation"]):
            return "travel_planning"
        if any(w in q for w in ["weather", "temperature", "forecast"]):
            return "weather_inquiry"
        if any(w in q for w in ["hiking", "cycling", "sightseeing", "food"]):
            return "activity_inquiry"
        return "general_query"

    def _execute(self, tool_name: str, args: dict) -> dict:
        try:
            if tool_name == "weather_current":
                return tool_weather(**args)
            elif tool_name == "activity_search":
                return tool_activity_search(**args)
            elif tool_name == "safety_check":
                return tool_safety_check(**args)
            elif tool_name == "summarize":
                return tool_summarize(**args)
            elif tool_name == "memory_store":
                return tool_memory_store(**args)
            elif tool_name == "memory_retrieve":
                return tool_memory_retrieve(**args)
            else:
                return {"error": True, "message": f"Unknown tool: {tool_name}"}
        except Exception as e:
            return {"error": True, "message": str(e), "tool": tool_name}

    def _decide(self, tool_name: str, result: dict, step_index: int) -> str:
        if result.get("error"):
            if step_index >= self.max_steps - 2:
                return "output"
            return "retry"

        if tool_name == "summarize":
            return "output"

        if tool_name == "weather_current" and not result.get("error"):
            return "continue"

        if tool_name == "activity_search":
            return "continue"

        if tool_name == "safety_check":
            return "continue"

        if step_index >= self.max_steps - 1:
            return "output"

        return "continue"


# ============================================================
# Demo entry point
# ============================================================

agent = TravelPlanner()


def run_demo():
    """Run the Travel Planner demo — generates trace for UI."""
    from agent_obs.trace_export import TraceExport
    from agent_obs.trace_diff import TraceDiffer, render_causal_verdict
    from agent_obs.frontend_adapter import adapt_diff_result
    from agent_obs.trace_core import explain_diff

    print("=" * 65)
    print("  Travel Planner Agent — AgentTrace Demo")
    print("=" * 65)
    print()

    # ── Run A: Tokyo (correct) ──
    print("[Run A] Trip to Tokyo for hiking")
    agent_a = TravelPlanner(enable_bug=False, max_steps=8)
    traced_a = TracedAgent(agent_a, out_dir=".")
    result_a = traced_a.run("Plan a trip to Tokyo for hiking")
    print(f"  Result: {result_a[:120]}")
    export_a = TraceExport.from_file(traced_a.last_trace_path)
    print()

    # ── Run B: Paris (bug triggers, cascade exhausts budget) ──
    print("[Run B] Trip to Paris for hiking")
    agent_b = TravelPlanner(enable_bug=True, max_steps=5)
    traced_b = TracedAgent(agent_b, out_dir=".")
    result_b = traced_b.run("Plan a trip to Paris for hiking")
    print(f"  Result: {result_b[:120]}")
    export_b = TraceExport.from_file(traced_b.last_trace_path)
    print()

    # ── Diff ──
    differ = TraceDiffer(export_a, export_b)
    diff_result = differ.diff()
    if traced_a.last_ctx and traced_b.last_ctx:
        diff_result.causal_narrative = explain_diff(traced_a.last_ctx, traced_b.last_ctx)

    # ── Render verdict (CLI) ──
    print(render_causal_verdict(diff_result))

    # ── Export unified JSON for UI ──
    ui_json = adapt_diff_result(diff_result, export_a, export_b)
    out_path = os.path.join(os.path.dirname(__file__), "..", "agent-trace-ui", "public", "demo_trace.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ui_json, f, indent=2, ensure_ascii=False)
    print(f"\n  UI trace exported to: {out_path}")
    print(f"  Open http://localhost:5173 to view in DevTools UI")

    # Cleanup
    for t in [traced_a.last_trace_path, traced_b.last_trace_path]:
        try:
            os.remove(t)
        except OSError:
            pass


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Travel Planner Agent Demo")
    p.add_argument("--correct", action="store_true", help="Run both without bug (baseline)")
    p.add_argument("--tokyo", action="store_true", help="Run Tokyo trip only")
    p.add_argument("--paris", action="store_true", help="Run Paris trip only (triggers bug)")
    p.add_argument("--export", action="store_true", help="Export trace to JSON for UI")
    args = p.parse_args()

    if args.correct:
        # Both runs without bug — should produce identical-ish paths
        for city, seed in [("Tokyo", 100), ("Paris", 200)]:
            agent = TravelPlanner(enable_bug=False, max_steps=8)
            traced = TracedAgent(agent, out_dir=".")
            result = traced.run(f"Plan a trip to {city} for hiking")
            print(f"[{city}] {result[:120]}")
            try:
                os.remove(traced.last_trace_path)
            except OSError:
                pass
    elif args.tokyo:
        agent = TravelPlanner(enable_bug=False)
        traced = TracedAgent(agent, out_dir=".")
        result = traced.run("Plan a trip to Tokyo for hiking")
        print(f"[Tokyo] {result[:200]}")
    elif args.paris:
        agent = TravelPlanner(enable_bug=True)
        traced = TracedAgent(agent, out_dir=".")
        result = traced.run("Plan a trip to Paris for hiking")
        print(f"[Paris] {result[:200]}")
    elif args.export:
        run_demo()
    else:
        run_demo()
