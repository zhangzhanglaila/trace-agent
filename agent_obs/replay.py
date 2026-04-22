"""Fork and re-run agent from saved state."""


class ReplayEngine:
    def __init__(self, instrumentor):
        self.instrumentor = instrumentor

    async def fork_and_rerun(self, step: int, modified_output: str):
        # Find state snapshot
        snapshot = None
        for event in self.instrumentor.emitter.events:
            if event.type == "state_snapshot" and event.data["step"] == step:
                snapshot = event.data
                break

        if not snapshot:
            raise ValueError(f"No snapshot at step {step}")

        messages = snapshot["messages"].copy()

        # Replace last tool result with modified output
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "tool":
                messages[i] = {
                    "role": "tool",
                    "name": messages[i].get("name"),
                    "content": modified_output
                }
                break

        fork_id = f"fork_{len(self.instrumentor.emitter.forks)}"
        self.instrumentor.emitter.forks[fork_id] = {"parent_step": step, "messages": messages}

        await self.instrumentor.run_from_state(messages)
        return fork_id
