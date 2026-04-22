import asyncio
import time
from dataclasses import dataclass, asdict

@dataclass
class TraceEvent:
    step: int
    type: str
    timestamp: float
    data: dict


class EventEmitter:
    def __init__(self, trace_id: str, ws_sender=None):
        self.trace_id = trace_id
        self.events = []
        self.is_paused = False
        self.current_step = 0
        self.forks = {}
        self.ws_sender = ws_sender

    async def emit(self, event_type: str, data: dict):
        """Emit event - NO pause check here (only at checkpoints)."""
        event = TraceEvent(
            step=self.current_step,
            type=event_type,
            timestamp=time.time(),
            data=data
        )
        self.events.append(event)
        self.current_step += 1

        if self.ws_sender:
            await self.ws_sender({
                "type": "event",
                "trace_id": self.trace_id,
                "event": asdict(event)
            })

    async def wait_if_paused(self):
        """Only called at 3 checkpoints - blocks if paused."""
        while self.is_paused:
            await asyncio.sleep(0.1)

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False
