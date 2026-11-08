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

async def _owner_visible(tenant_id: str, companion_id: str, end_user_id: str) -> tuple[list[dict], dict]:
    """What the BUSINESS may see through this character: the facts it can see under the current
    scope, minus any learned by a privacy-mode-B character (in business scope those are shared
    with the characters, never with the owner). Also returns the tenant's characters by id."""
    from app.companion import store
    from app.companion.memory_card import visible_facts

    characters = {c["id"]: c for c in await store.list_companions(tenant_id)}
    facts = [f for f in await visible_facts(tenant_id, companion_id, end_user_id)
             if characters.get(f["companion_id"], {}).get("privacy_mode", "A") == "A"]
    return facts, characters


async def list_memory(tenant_id: str, companion_id: str, external_user_id: str):
    """What the owner sees this character remember about the person: the current scope, newest
    first, own facts first, never a mode-B character's facts. [] for an unknown person.
    Raises LookupError for another tenant's character."""
    from app.companion import store
    from app.companion.models import MemoryFact

    if not await store.get_companion(tenant_id, companion_id):
        raise LookupError("character not found")
    person = await store.find_end_user(tenant_id, external_user_id)
    if not person:
        return []
    facts, characters = await _owner_visible(tenant_id, companion_id, person["id"])
    return [
        MemoryFact(id=str(f["id"]), section=f["section"], text=f["text"],
                   valid_from=f.get("valid_from"), valid_to=f.get("valid_to"), status=f["status"],
                   learned_by=characters.get(f["companion_id"], {}).get("name", "another character"))
        for f in facts
    ]


async def forget_fact(tenant_id: str, companion_id: str, external_user_id: str, fact_id: str) -> bool:
    """The owner deletes one fact they can see (list_memory's rules). False otherwise: wrong
    person, wrong tenant, another character's fact in character scope, or a mode-B character's."""
    from app.companion import store

    person = await store.find_end_user(tenant_id, external_user_id)
    if not person:
        return False
    facts, _ = await _owner_visible(tenant_id, companion_id, person["id"])
    if fact_id not in {str(f["id"]) for f in facts}:
        return False
    return await store.delete_fact(tenant_id, fact_id)
