"""Working memory for the research agent."""


class AgentMemory:
    """Stores intermediate results across agent steps."""

    def __init__(self):
        self._store: dict = {}
        self._history: list = []

    def set(self, key: str, value):
        self._store[key] = value
        self._history.append(("set", key, str(value)[:80]))

    def get(self, key: str):
        return self._store.get(key)

    def has(self, key: str) -> bool:
        return key in self._store

    def snapshot(self) -> dict:
        return {
            "store_keys": list(self._store.keys()),
            "history_length": len(self._history),
            "last_action": self._history[-1] if self._history else None,
        }

    def clear(self):
        self._store.clear()
        self._history.clear()
