"""Web search tool — simulated for demo."""

import time
import random


def web_search(query: str) -> dict:
    """
    Search the web for a query. Returns structured results.

    Simulates a real search API with variable latency.
    """
    time.sleep(0.05)

    # Simulated search results based on query keywords
    results = []
    query_lower = query.lower()

    if "climate" in query_lower or "weather" in query_lower:
        results = [
            {"title": "Global Climate Report 2025", "url": "/climate/2025", "snippet": "Rising temperatures..."},
            {"title": "Renewable Energy Growth", "url": "/energy/renewable", "snippet": "Solar and wind capacity..."},
            {"title": "Climate Policy Updates", "url": "/policy/climate", "snippet": "New regulations on emissions..."},
        ]
    elif "ai" in query_lower or "machine learning" in query_lower:
        results = [
            {"title": "AI Safety Standards", "url": "/ai/safety", "snippet": "New framework for AI governance..."},
            {"title": "ML in Production 2025", "url": "/ml/production", "snippet": "Best practices for deploying ML..."},
            {"title": "Transformer Architecture v2", "url": "/ml/transformers", "snippet": "Next-gen attention mechanisms..."},
            {"title": "AI Regulation Update", "url": "/policy/ai", "snippet": "EU AI Act implementation..."},
            {"title": "Open Source LLMs Compared", "url": "/llm/comparison", "snippet": "Benchmarking open models..."},
        ]
    elif "database" in query_lower or "sql" in query_lower:
        results = [
            {"title": "PostgreSQL 17 Released", "url": "/db/postgres17", "snippet": "New features in PostgreSQL..."},
            {"title": "NoSQL vs SQL in 2025", "url": "/db/comparison", "snippet": "Choosing the right database..."},
        ]
    else:
        results = [
            {"title": f"Result 1 for: {query}", "url": "/r1", "snippet": f"Information about {query}..."},
            {"title": f"Result 2 for: {query}", "url": "/r2", "snippet": f"More about {query}..."},
        ]

    return {
        "query": query,
        "results": results,
        "total_count": len(results),
        "search_time_ms": random.randint(40, 200),
    }
