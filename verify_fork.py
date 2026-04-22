"""
Verify fork works - THIS IS THE DOORS TEST.
If this fails, nothing else matters.
Run: python verify_fork.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from agent_obs import observe

CASE_NORMAL = "CASE_NORMAL"
CASE_CRITICAL = "CASE_CRITICAL"


class MedicalTriageAgent:
    """Medical triage with guaranteed fork behavior."""

    def __init__(self):
        self.tools = {"diagnose": self.diagnose}

    def diagnose(self, symptoms: str) -> str:
        if "mild" in symptoms.lower():
            return CASE_NORMAL
        return CASE_CRITICAL

    async def llm_think(self, messages: list) -> dict:
        recent_tool = None
        for msg in reversed(messages):
            if msg.get("role") == "tool":
                recent_tool = msg.get("content")
                break

        # HARD BRANCH - no fuzzy matching
        if recent_tool == CASE_CRITICAL:
            return {
                "thought": "CRITICAL EMERGENCY DETECTED",
                "action": None,
                "content": "EMERGENCY PROTOCOL: CALL 911 IMMEDIATELY"
            }
        elif recent_tool == CASE_NORMAL:
            return {
                "thought": "Non-emergency condition detected",
                "action": None,
                "content": "Patient presents with non-emergency symptoms. Rest and fluids."
            }
        else:
            return {
                "thought": "Analyzing symptoms",
                "action": "diagnose",
                "action_input": {"symptoms": messages[-1]["content"]}
            }

    async def call_tool(self, tool_name: str, args: dict) -> str:
        return self.tools[tool_name](**args)

    async def run(self, query: str):
        messages = [{"role": "user", "content": query}]
        for _ in range(10):
            response = await self.llm_think(messages)
            if not response.get("action"):
                return response.get("content", "")
            result = await self.call_tool(response["action"], response.get("action_input", {}))
            messages.append({"role": "tool", "name": response["action"], "content": result})
        return "Max steps"


async def main():
    print("=" * 60)
    print("VERIFYING FORK BEHAVIOR")
    print("=" * 60)

    # Test 1: Original path
    print("\n[1] Original path (CASE_NORMAL)...")
    agent1 = MedicalTriageAgent()
    traced1 = observe(agent1)
    result1 = await traced1.run("Patient has mild discomfort")
    print(f">>> {result1[:60]}...")

    # Test 2: Forked path
    print("\n[2] Forked path (CASE_CRITICAL)...")
    agent2 = MedicalTriageAgent()
    traced2 = observe(agent2)

    messages = [{"role": "user", "content": "Patient has mild discomfort"}]
    await agent2.llm_think(messages)
    tool_result = agent2.tools["diagnose"]("mild discomfort")
    messages.append({"role": "tool", "name": "diagnose", "content": tool_result})

    # THE FORK: Change CASE flag
    messages[-1] = {"role": "tool", "name": "diagnose", "content": CASE_CRITICAL}

    result2 = await traced2._instrumentor.run_from_state(messages)
    print(f">>> {result2[:60]}...")

    # Verify
    print("\n" + "=" * 60)
    if "911" in result2 and "rest" in result1.lower():
        print("[OK] FORK VERIFIED - Demo will work!")
        print("   Original: 'rest and fluids'")
        print("   Forked:   'CALL 911'")
    else:
        print("[FAIL] FORK FAILED - Fix agent logic first")
        print(f"   result1: {result1}")
        print(f"   result2: {result2}")


if __name__ == "__main__":
    asyncio.run(main())
