"""Knowledge base tools: fact verification and structured queries."""

import time
import random


# Simulated knowledge base
_KNOWLEDGE_BASE = {
    "postgresql": {"version": "17", "type": "relational", "license": "open source"},
    "transformer": {"invented": 2017, "type": "architecture", "variants": ["BERT", "GPT", "T5"]},
    "climate": {"warming_trend": "+1.2C", "since": "pre-industrial", "confidence": "high"},
    "renewable_energy": {"solar_growth": "24% YoY", "wind_growth": "12% YoY", "year": 2025},
    "ai_regulation": {"eu_ai_act": "enacted", "us_executive_order": "2023", "status": "active"},
}


def verify_facts(facts: list) -> dict:
    """
    Cross-check extracted facts against the knowledge base.

    Returns verification status for each fact.
    """
    time.sleep(0.04)

    if not facts:
        return {"verified": [], "unverified": [], "status": "no_facts"}

    verified = []
    unverified = []
    for f in facts:
        claim = f.get("claim", "").lower()
        matched = False
        for key, info in _KNOWLEDGE_BASE.items():
            if key in claim:
                verified.append({**f, "kb_match": key, "kb_data": info})
                matched = True
                break
        if not matched:
            unverified.append(f)

    return {
        "verified": verified,
        "unverified": unverified,
        "verified_count": len(verified),
        "unverified_count": len(unverified),
        "status": "success",
    }


def query_knowledge_base(topic: str) -> dict:
    """Direct query to the knowledge base."""
    time.sleep(0.02)

    topic_lower = topic.lower()
    for key, info in _KNOWLEDGE_BASE.items():
        if key in topic_lower:
            return {"found": True, "topic": key, "data": info}

    return {"found": False, "topic": topic, "data": None}
