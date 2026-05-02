"""
AgentTrace — Chrome DevTools for AI Agents.

We turn agent execution into a causal graph,
and explain WHY two runs diverge.

Usage:
    from agenttrace import enable, dev
    enable()
"""

from agent_obs.enable import enable, dev

__all__ = ["enable", "dev"]
