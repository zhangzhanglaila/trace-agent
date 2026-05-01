"""Planner — decision logic for the research agent.

CONTAINS BUG: The routing threshold check at `_should_skip_extraction`
uses `len(search_results)` instead of `len(facts)`, causing the agent to
skip fact extraction when search returns many results (5+). This means
raw search snippets are fed directly to summarize, producing incomplete
or misleading output.
"""

from demo_agent.memory import AgentMemory

# Bug switch (controlled via --bug flag or env var)
PLANNER_BUG_ENABLED = True


def _should_skip_extraction(memory: AgentMemory) -> bool:
    """
    Decide whether to skip the fact extraction step.

    BUG: When PLANNER_BUG_ENABLED is True, this checks the WRONG variable.
    It checks `search_results` count (raw results) instead of `facts` count
    (extracted facts). Many raw results ≠ many verified facts.

    Correct behavior: skip only if facts are already extracted.
    Bug behavior: skip if raw search results seem "sufficient" (>= 4).
    """
    if not PLANNER_BUG_ENABLED:
        # Correct: only skip if facts already exist
        return memory.has("facts")

    # BUG: checks search result count instead of facts
    search_data = memory.get("search_results")
    if search_data and isinstance(search_data, dict):
        raw_count = search_data.get("total_count", 0)
        if raw_count >= 4:
            # Incorrectly assumes many results = enough data
            return True
    return False


def plan_next(memory: AgentMemory) -> dict:
    """
    Decide the next tool to call based on current state.

    Returns a dict with:
        tool: name of the tool to call
        args: arguments for the tool
        reasoning: why this tool was chosen
    """
    # If summary already produced, we're done
    if memory.has("summary"):
        return {
            "tool": "done",
            "args": {},
            "reasoning": "Summary produced — pipeline complete",
        }

    # Step 0: If no search done yet, start with search
    if not memory.has("search_results"):
        topic = memory.get("topic") or "general research"
        return {
            "tool": "web_search",
            "args": {"query": topic},
            "reasoning": "No data yet — starting with web search",
        }

    # Step 1: After search, extract facts (unless bug skips it)
    if memory.has("search_results") and not memory.has("facts"):
        if _should_skip_extraction(memory):
            # BUG PATH: skip directly to summarize
            return {
                "tool": "summarize",
                "args": {
                    "search_data": memory.get("search_results"),
                    "source": "raw_search_results",
                },
                "reasoning": "Search returned sufficient results — summarizing directly (BUG: skipping fact extraction)",
            }

        # CORRECT PATH: extract facts from search results
        return {
            "tool": "extract_facts",
            "args": {"search_results": memory.get("search_results").get("results", [])},
            "reasoning": "Search complete — extracting structured facts",
        }

    # Step 2: After fact extraction, verify against knowledge base
    if memory.has("facts") and not memory.has("verified_facts"):
        facts_data = memory.get("facts")
        return {
            "tool": "verify_facts",
            "args": {"facts": facts_data.get("facts", [])},
            "reasoning": "Facts extracted — verifying against knowledge base",
        }

    # Step 3: After verification, analyze sentiment
    if memory.has("verified_facts") and not memory.has("sentiment"):
        facts_data = memory.get("facts")
        return {
            "tool": "analyze_sentiment",
            "args": {"facts": facts_data.get("facts", [])},
            "reasoning": "Facts verified — analyzing sentiment distribution",
        }

    # Step 4: All data collected — summarize
    if memory.has("sentiment") and not memory.has("summary"):
        return {
            "tool": "summarize",
            "args": {
                "facts": memory.get("facts"),
                "verified": memory.get("verified_facts"),
                "sentiment": memory.get("sentiment"),
                "topic": memory.get("topic"),
            },
            "reasoning": "All data collected — producing final summary",
        }

    # Fallback: done
    return {
        "tool": "done",
        "args": {},
        "reasoning": "Pipeline complete",
    }
