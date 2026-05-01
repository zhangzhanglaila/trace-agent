"""Analysis tools: fact extraction and sentiment analysis."""

import time
import random


def extract_facts(search_results: list) -> dict:
    """
    Extract structured facts from search results.

    This is a critical step — without it, downstream tools get raw unstructured data.
    """
    time.sleep(0.03)

    if not search_results:
        return {"facts": [], "count": 0, "status": "empty"}

    facts = []
    for r in search_results:
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        facts.append({
            "source": title,
            "claim": snippet,
            "confidence": round(random.uniform(0.6, 0.95), 2),
        })

    return {
        "facts": facts,
        "count": len(facts),
        "status": "success",
        "extraction_time_ms": random.randint(20, 80),
    }


def analyze_sentiment(facts: list) -> dict:
    """
    Analyze sentiment of extracted facts.

    Returns sentiment distribution across fact claims.
    """
    time.sleep(0.02)

    if not facts:
        return {"sentiment": "neutral", "distribution": {}, "confidence": 0.0}

    sentiments = []
    for f in facts:
        claim = f.get("claim", "").lower()
        if any(w in claim for w in ["growth", "released", "best", "new", "safety"]):
            sentiments.append("positive")
        elif any(w in claim for w in ["regulation", "emissions", "risk", "warning"]):
            sentiments.append("negative")
        else:
            sentiments.append("neutral")

    dist = {
        "positive": sentiments.count("positive"),
        "negative": sentiments.count("negative"),
        "neutral": sentiments.count("neutral"),
    }

    dominant = max(dist, key=dist.get) if dist else "neutral"

    return {
        "sentiment": dominant,
        "distribution": dist,
        "confidence": round(dist[dominant] / len(sentiments), 2) if sentiments else 0.0,
    }
