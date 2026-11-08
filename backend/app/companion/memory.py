"""Memory slot. Level 1 = plain recent history (read by the engine via store.recent_messages);
companion-memory adds Level 2/3 providers behind this same protocol later."""
from typing import Protocol


class MemoryProvider(Protocol):
    async def context_for(self, companion_id: str, end_user_id: str, message: str) -> str: ...
    async def record_turn(self, companion_id: str, end_user_id: str, user_msg: str, reply: str) -> None: ...
    async def forget(self, end_user_id: str) -> None: ...


class Level1History:
    """Level 1: no extra memory beyond the last 10 messages, so every hook is a no-op."""

    async def context_for(self, companion_id: str, end_user_id: str, message: str) -> str:
        return ""

    async def record_turn(self, companion_id: str, end_user_id: str, user_msg: str, reply: str) -> None:
        return None

    async def forget(self, end_user_id: str) -> None:
        return None


def provider_for(memory_level: int) -> MemoryProvider:
    """Levels 1 and 2 both use plain history in v1; Level 3 is not built yet."""
    return Level1History()
