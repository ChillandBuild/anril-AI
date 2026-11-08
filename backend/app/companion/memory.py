"""Memory slot. Level 1 = plain recent history (read by the engine via store.recent_messages).
Level 2 = facts about the person, kept by an engine behind this same protocol: 'card' (ours,
memory_card.py) or 'mem0' (memory_mem0.py, later). Facts are written by the every-minute sweep
(memory_sweep.py), never on the reply path, so record_turn stays a no-op for every engine."""
from typing import Protocol


class MemoryProvider(Protocol):
    async def context_for(self, tenant_id: str, companion_id: str, end_user_id: str, message: str) -> str: ...
    async def record_turn(self, tenant_id: str, companion_id: str, end_user_id: str,
                          user_msg: str, reply: str) -> None: ...
    async def forget(self, tenant_id: str, end_user_id: str) -> None: ...


class Level1History:
    """Level 1: no extra memory beyond the last 10 messages, so every hook is a no-op."""

    async def context_for(self, tenant_id: str, companion_id: str, end_user_id: str, message: str) -> str:
        return ""

    async def record_turn(self, tenant_id: str, companion_id: str, end_user_id: str,
                          user_msg: str, reply: str) -> None:
        return None

    async def forget(self, tenant_id: str, end_user_id: str) -> None:
        return None


def provider_for(memory_level: int, engine: str = "card") -> MemoryProvider:
    """Level 1 → plain history. Level 2 → the character's engine (only 'card' is built so far;
    'mem0' falls back to the card until memory_mem0.py lands)."""
    if memory_level >= 2:
        from app.companion.memory_card import MemoryCard
        return MemoryCard()
    return Level1History()


def forget_providers() -> list[MemoryProvider]:
    """Every engine that may hold facts. 'Forget me' tells all of them, whatever the current
    setting, because a past setting may have left facts in another engine."""
    from app.companion.memory_card import MemoryCard
    return [MemoryCard()]
