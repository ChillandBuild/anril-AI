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


# --- seeing and forgetting facts (spec §3.6). Card engine only until Mem0 lands. ----------------

async def list_memory(tenant_id: str, companion_id: str, external_user_id: str):
    """What this character remembers about the person under the current scope, newest first,
    own facts first. [] for an unknown person. Raises LookupError for another tenant's character."""
    from app.companion import store
    from app.companion.memory_card import visible_facts
    from app.companion.models import MemoryFact

    if not await store.get_companion(tenant_id, companion_id):
        raise LookupError("character not found")
    person = await store.find_end_user(tenant_id, external_user_id)
    if not person:
        return []
    names = {c["id"]: c["name"] for c in await store.list_companions(tenant_id)}
    return [
        MemoryFact(id=str(f["id"]), section=f["section"], text=f["text"],
                   valid_from=f.get("valid_from"), valid_to=f.get("valid_to"), status=f["status"],
                   learned_by=names.get(f["companion_id"], "another character"))
        for f in await visible_facts(tenant_id, companion_id, person["id"])
    ]


async def forget_fact(tenant_id: str, companion_id: str, external_user_id: str, fact_id: str) -> bool:
    """Deletes one fact this character can see about the person. False if there's no such fact
    for them (wrong person, wrong tenant, or another character's fact in character scope)."""
    from app.companion import store
    from app.companion.memory_card import visible_facts

    person = await store.find_end_user(tenant_id, external_user_id)
    if not person:
        return False
    visible = {str(f["id"]) for f in await visible_facts(tenant_id, companion_id, person["id"])}
    if fact_id not in visible:
        return False
    return await store.delete_fact(tenant_id, fact_id)
