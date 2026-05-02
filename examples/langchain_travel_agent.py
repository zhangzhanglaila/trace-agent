"""
LangChain-Style Multi-Tool Travel Agent — AgentTrace Killer Demo.

Mirrors real LangChain tool-calling agent patterns:
  - @tool decorators with typed outputs
  - Structured tool results with confidence scores
  - LLM planner/routing between tools
  - Conversation memory (store/retrieve)

THE BUG — "Ambiguous Tool Output"

weather_current returns empty condition for unknown cities (Mars).
The routing logic treats "" (empty string) as "no constraints" and defaults
to outdoor activities, which is the WRONG assumption. The correct behavior
is to treat unknown weather as a signal to default to indoor (safe fallback).

REAL-WORLD ANALOGY:
  - API returning null instead of error for missing data
  - LLM misinterpreting ambiguous tool output
  - Router not handling edge cases in tool responses

This is exactly the kind of bug that AgentTrace's causal graph diff
pinpoints: "A returned 'clear', B returned '' → decision flipped →
downstream output diverged."

Usage:
    python examples/langchain_travel_agent.py              # Demo with bug
    python examples/langchain_travel_agent.py --correct    # Baseline (no bug)
    python examples/langchain_travel_agent.py --cli        # CLI verdict only
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_obs.trace_core import trace_span, trace_decision, SEM, TracedAgent


# ============================================================
# Knowledge Base
# ============================================================

WEATHER_DB = {
    "tokyo":     {"city": "Tokyo",     "temp": 22, "condition": "sunny",  "humidity": 55},
    "paris":     {"city": "Paris",     "temp": 14, "condition": "cloudy", "humidity": 68},
    "london":    {"city": "London",    "temp": 10, "condition": "rain",   "humidity": 82},
    "new york":  {"city": "New York",  "temp": 18, "condition": "sunny",  "humidity": 45},
    "sydney":    {"city": "Sydney",    "temp": 24, "condition": "clear",  "humidity": 50},
    "bangkok":   {"city": "Bangkok",   "temp": 34, "condition": "hot",    "humidity": 75},
    "reykjavik": {"city": "Reykjavik", "temp": 3,  "condition": "cold",   "humidity": 70},
}

HOTEL_DB = {
    "tokyo":     ["Shinjuku Grand Hotel", "Shibuya Stream Inn", "Asakusa View"],
    "paris":     ["Le Marais Boutique", "Montmartre Suites", "Latin Quarter Hotel"],
    "london":    ["Westminster Grand", "Soho House", "Covent Garden Inn"],
    "new york":  ["Midtown Luxe", "Brooklyn Lofts", "SoHo Grand"],
    "sydney":    ["Harbour View Hotel", "Bondi Beach Resort", "The Rocks Inn"],
    "bangkok":   ["Riverside Palace", "Sukhumvit Suites", "Silom Grand"],
    "reykjavik": ["Northern Light Inn", "Reykjavik Central", "Blue Lagoon Resort"],
}

ACTIVITY_DB = {
    "outdoor": {
        "tokyo":     "Mount Takao hiking trail (3h, moderate). Cherry blossoms in full bloom.",
        "paris":     "Seine riverside walk + Luxembourg Gardens (2h, easy).",
        "london":    "Hyde Park loop + Thames Path (3h, easy).",
        "new york":  "Central Park full loop + High Line walk (2.5h, easy).",
        "sydney":    "Bondi to Coogee coastal walk (2h, moderate). Stunning ocean views.",
        "bangkok":   "Lumphini Park morning walk (1h, easy). Bring water — very hot.",
        "reykjavik": "Northern Lights walk (2h, weather dependent). Dress in layers.",
    },
    "indoor": {
        "tokyo":     "teamLab Borderless digital art + Tsukiji food tour.",
        "paris":     "Louvre Museum + Le Marais covered passages shopping.",
        "london":    "British Museum + Tate Modern + Borough Market food hall.",
        "new york":  "Metropolitan Museum + Chelsea Market + Broadway matinee.",
        "sydney":    "Sydney Opera House tour + Rocks Discovery Museum.",
        "bangkok":   "Grand Palace + Wat Pho temple + Siam Paragon shopping.",
        "reykjavik": "Harpa Concert Hall + Perlan Museum + Sky Lagoon geothermal spa.",
    },
}

SAFETY_NOTES = {
    "outdoor": {
        "sunny": "Safe. Bring water and sunscreen.",
        "clear": "Safe. Standard outdoor precautions apply.",
        "cloudy": "Safe. Bring a rain jacket just in case.",
        "rain": "CAUTION: slippery surfaces. Wear proper footwear.",
        "hot": "WARNING: heat risk. Hike early morning only, bring 2L+ water.",
        "cold": "DANGER: hypothermia risk. Full winter gear required.",
        "": "UNKNOWN: cannot assess outdoor safety without weather data.",
    },
    "indoor": {
        "sunny": "Safe. Indoor venues are air-conditioned.",
        "clear": "Safe. No weather concerns indoors.",
        "cloudy": "Safe. Indoor activities unaffected.",
        "rain": "Safe. Indoor venues provide shelter.",
        "hot": "Safe. Air-conditioned indoor spaces recommended.",
        "cold": "Safe. Heated indoor venues available.",
        "": "Safe. Indoor activities are weather-independent.",
    },
}


# ============================================================
# Tools (decorated with trace_span for rich execution graph)
# ============================================================

def tool_weather_current(city: str) -> dict:
    """Get current weather conditions for a city."""
    with trace_span("weather_current", SEM.TOOL,
                    inputs={"city": city}) as span:
        key = city.lower().strip()
        data = WEATHER_DB.get(key)

        if data is None:
            # Edge case: city not in database.
            # BUG-ADJACENT: returns empty condition instead of explicit error.
            # The router must handle this ambiguity correctly.
            result = {
                "city": city,
                "temp": 0,
                "condition": "",
                "humidity": 0,
                "found": False,
                "confidence": "low",
                "needs_clarification": True,
            }
        else:
            result = {
                **data,
                "found": True,
                "confidence": "high",
                "needs_clarification": False,
            }

        span["outputs"] = {"result": result}
        span["produces"] = {"weather_result": result}
        return result


def tool_search_activities(destination: str, activity_type: str) -> dict:
    """Search for activities based on destination and indoor/outdoor preference."""
    with trace_span("search_activities", SEM.TOOL,
                    inputs={"destination": destination,
                            "activity_type": activity_type}) as span:
        key = destination.lower().strip()
        act_list = ACTIVITY_DB.get(activity_type, {})
        recommendation = act_list.get(key, f"Generic {activity_type} options available in {destination}.")

        result = {
            "destination": destination,
            "activity_type": activity_type,
            "recommendation": recommendation,
            "found": key in act_list,
        }
        span["outputs"] = {"result": result}
        span["produces"] = {"activity_result": result}
        return result


def tool_search_hotels(destination: str) -> dict:
    """Search for hotels at the destination."""
    with trace_span("search_hotels", SEM.TOOL,
                    inputs={"destination": destination}) as span:
        key = destination.lower().strip()
        hotels = HOTEL_DB.get(key, [f"Generic hotel in {destination}"])

        result = {
            "destination": destination,
            "hotels": hotels,
            "count": len(hotels),
            "found": key in HOTEL_DB,
        }
        span["outputs"] = {"result": result}
        span["produces"] = {"hotel_result": result}
        return result


def tool_safety_check(activity_type: str, weather_condition: str) -> dict:
    """Check safety for planned activities given weather conditions."""
    with trace_span("safety_check", SEM.TOOL,
                    inputs={"activity_type": activity_type,
                            "weather_condition": weather_condition}) as span:
        type_notes = SAFETY_NOTES.get(activity_type, {})
        note = type_notes.get(weather_condition, type_notes.get("", "No specific safety data."))

        is_danger = note.startswith("DANGER")
        is_caution = note.startswith("CAUTION") or note.startswith("WARNING") or note.startswith("UNKNOWN")

        result = {
            "activity_type": activity_type,
            "weather_condition": weather_condition,
            "note": note,
            "safe": not is_danger,
            "level": "danger" if is_danger else ("caution" if is_caution else "safe"),
        }
        span["outputs"] = {"result": result}
        span["produces"] = {"safety_result": result}
        return result


def tool_build_plan(city: str, weather: dict, activities: dict,
                    hotels: dict, safety: dict) -> dict:
    """Assemble the final travel plan from all collected data."""
    with trace_span("build_plan", SEM.CHAIN,
                    inputs={"city": city, "weather": weather,
                            "activities": activities, "hotels": hotels,
                            "safety": safety}) as span:
        # If safety check failed, plan is partial
        if safety.get("level") == "danger":
            result = {
                "status": "FAIL",
                "city": city,
                "plan": f"Cannot proceed: {safety['note']}",
                "sections": [],
            }
        elif safety.get("level") == "caution" or not weather.get("found"):
            result = {
                "status": "PARTIAL",
                "city": city,
                "warning": safety.get("note", "Weather data incomplete"),
                "sections": [
                    f"Weather: {weather.get('condition', 'unknown')}, {weather.get('temp', 'N/A')}C",
                    f"Activities: {activities.get('recommendation', 'None')}",
                    f"Hotels: {', '.join(hotels.get('hotels', [])[:2])}",
                ],
            }
        else:
            result = {
                "status": "OK",
                "city": city,
                "sections": [
                    f"Weather: {weather.get('condition')}, {weather.get('temp')}C, humidity {weather.get('humidity')}%",
                    f"Activities ({activities.get('activity_type')}): {activities.get('recommendation')}",
                    f"Hotels: {', '.join(hotels.get('hotels', []))}",
                    f"Safety: {safety.get('note')}",
                ],
            }

        span["outputs"] = {"result": result}
        span["produces"] = {"plan_result": result}
        return result


# ============================================================
# Agent
# ============================================================

class LangChainTravelAgent:
    """
    Multi-tool travel planning agent — LangChain style.

    Pipeline:
      classify_intent → weather → decide_activity_type →
      search_activities → search_hotels → safety_check → build_plan

    Each tool is a standalone function with trace_span instrumentation,
    exactly like a LangChain @tool decorated function.
    """

    def __init__(self, enable_bug: bool = True):
        self.enable_bug = enable_bug
        self.memory: dict = {}

    def run(self, query: str) -> str:
        """Execute the full travel planning pipeline."""
        import re

        # Extract city from query
        city_match = re.search(r'to\s+([A-Za-z\s]+?)(?:\s+for|\s*$)', query)
        city = city_match.group(1).strip() if city_match else "unknown"

        # Step 1: Classify intent
        with trace_span("classify_intent", SEM.LLM,
                        inputs={"query": query}) as span:
            intent = "travel_planning" if any(
                w in query.lower() for w in ["trip", "travel", "plan", "visit"]
            ) else "general"
            span["outputs"] = {"result": intent}
            span["produces"] = {"intent": intent}

        # Step 2: Get weather — CRITICAL STEP (bug lives downstream of this)
        weather = tool_weather_current(city)

        # Step 3: Decide indoor vs outdoor — WHERE THE BUG LIVES
        condition = weather.get("condition", "")
        confidence = weather.get("confidence", "")
        needs_clarification = weather.get("needs_clarification", False)

        with trace_span("decide_activity_type", SEM.LLM,
                        inputs={"condition": condition,
                                "confidence": confidence,
                                "needs_clarification": needs_clarification}) as span:

            if condition in ("sunny", "clear", "partly cloudy"):
                activity_type = "outdoor"
                decision_reason = f"Good weather ({condition}) → outdoor activities"
            elif condition in ("rain", "snow", "cloudy", "hot", "cold"):
                activity_type = "indoor"
                decision_reason = f"Weather is {condition} → indoor activities (safer)"
            else:
                # ═══════════════════════════════════════════════════════════
                # THE BUG: condition is "" (empty) for unknown cities.
                #
                # Buggy version: treats "" as "no constraints" → outdoor (WRONG)
                # Correct version: treats "" as "unknown" → indoor (SAFE FALLBACK)
                # ═══════════════════════════════════════════════════════════
                if self.enable_bug:
                    activity_type = "outdoor"
                    decision_reason = (
                        f"BUG: condition='{condition}' (empty) misinterpreted as "
                        f"'no constraints' → defaulting to outdoor. "
                        f"Should have treated as 'unknown weather' → indoor."
                    )
                else:
                    activity_type = "indoor"
                    decision_reason = (
                        f"Condition='{condition}' (empty/unknown) — "
                        f"defaulting to indoor as safe fallback."
                    )

            span["outputs"] = {"result": activity_type}
            span["produces"] = {"activity_type": activity_type,
                                "decision_reason": decision_reason}

        # Record the semantic decision (for SCM causal model)
        trace_decision(
            "decide_outdoor_vs_indoor",
            value=(activity_type == "outdoor"),
            consumes={"weather_condition": condition,
                      "weather_confidence": confidence},
            true_branch="search_outdoor_activities",
            false_branch="search_indoor_activities",
        )

        # Step 4: Search activities
        activities = tool_search_activities(city, activity_type)

        # Step 5: Search hotels
        hotels = tool_search_hotels(city)

        # Step 6: Safety check
        safety = tool_safety_check(activity_type, condition)

        # Step 7: Build final plan
        plan = tool_build_plan(city, weather, activities, hotels, safety)

        # Store in memory
        self.memory["last_plan"] = plan

        status = plan.get("status", "?")
        if status == "OK":
            return f"[OK] {city}: {plan['sections'][0]}; {plan['sections'][1][:80]}..."
        elif status == "PARTIAL":
            return f"[PARTIAL] {city}: {plan.get('warning', 'Plan incomplete')}"
        else:
            return f"[FAIL] {city}: {plan.get('plan', 'Plan failed')}"


# ============================================================
# Demo entry point
# ============================================================

agent = LangChainTravelAgent()


def run_demo(bug_enabled: bool = True, cli_only: bool = False):
    """Run the killer demo: Tokyo (control) vs Mars (reveals bug)."""
    from agent_obs.trace_export import TraceExport
    from agent_obs.trace_diff import TraceDiffer, render_causal_verdict
    from agent_obs.frontend_adapter import adapt_diff_result
    from agent_obs.trace_core import explain_diff

    print()
    print("=" * 60)
    print("  AgentTrace Killer Demo — LangChain Multi-Tool Agent")
    print(f"  Bug: {'ON  (weather ambiguity → wrong activity type)' if bug_enabled else 'OFF (baseline)'}")
    print("=" * 60)
    print()

    # ── Run A: Tokyo (always succeeds — real weather data) ──
    print("[Run A] Tokyo — has real weather data, agent works correctly")
    agent_a = LangChainTravelAgent(enable_bug=False)
    traced_a = TracedAgent(agent_a, out_dir=".")
    result_a = traced_a.run("Plan a trip to Tokyo for hiking")
    print(f"  => {result_a}")
    export_a = TraceExport.from_file(traced_a.last_trace_path)
    print()

    # ── Run B: Mars (no weather data — triggers the bug) ──
    city_b = "Mars"
    print(f"[Run B] {city_b} — no weather data, ambiguity triggers the bug")
    agent_b = LangChainTravelAgent(enable_bug=bug_enabled)
    traced_b = TracedAgent(agent_b, out_dir=".")
    result_b = traced_b.run(f"Plan a trip to {city_b} for hiking")
    print(f"  => {result_b}")
    export_b = TraceExport.from_file(traced_b.last_trace_path)
    print()

    # ── Diff ──
    differ = TraceDiffer(export_a, export_b)
    diff_result = differ.diff()
    if traced_a.last_ctx and traced_b.last_ctx:
        diff_result.causal_narrative = explain_diff(traced_a.last_ctx, traced_b.last_ctx)

    print(render_causal_verdict(diff_result))

    if not cli_only:
        # Export JSON for UI
        ui_json = adapt_diff_result(diff_result, export_a, export_b)
        ui_json["meta"]["bug_enabled"] = bug_enabled
        out_path = os.path.join(
            os.path.dirname(__file__), "..",
            "agent-trace-ui", "public", "demo_trace.json"
        )
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(ui_json, f, indent=2, ensure_ascii=False)
        print(f"\n  UI trace exported: {out_path}")
        print(f"  Open http://localhost:5173 to view in DevTools UI")

    # Cleanup
    for t in [traced_a.last_trace_path, traced_b.last_trace_path]:
        try:
            os.remove(t)
        except OSError:
            pass


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="LangChain Multi-Tool Agent — AgentTrace Killer Demo")
    p.add_argument("--correct", action="store_true", help="Run baseline (no bug)")
    p.add_argument("--cli", action="store_true", help="CLI-only verdict, no UI export")
    args = p.parse_args()

    run_demo(bug_enabled=not args.correct, cli_only=args.cli)
