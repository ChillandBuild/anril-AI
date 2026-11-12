"""Memory slot. Level 1 = plain recent history (read by the engine via store.recent_messages).
Level 2 = facts about the person, kept by an engine behind this same protocol: 'card' (ours,
memory_card.py) or 'mem0' (memory_mem0.py, later). Facts are written by the every-minute sweep
(memory_sweep.py), never on the reply path, so record_turn stays a no-op for every engine."""
import logging
from datetime import date, timedelta
from typing import Protocol

logger = logging.getLogger(__name__)


class MemoryProvider(Protocol):
    searches: bool   # True: context_for searches old chats, so the engine starts the shared rewrite for it

    async def context_for(self, tenant_id: str, companion_id: str, end_user_id: str, message: str,
                          *, companion: dict | None = None, person: dict | None = None,
                          rewrite=None) -> str: ...
    async def record_turn(self, tenant_id: str, companion_id: str, end_user_id: str,
                          user_msg: str, reply: str) -> None: ...
    async def forget(self, tenant_id: str, end_user_id: str) -> None: ...


class Level1History:
    """Level 1: no extra memory beyond the last 10 messages, so every hook is a no-op."""

    searches = False

    async def context_for(self, tenant_id: str, companion_id: str, end_user_id: str, message: str,
                          *, companion: dict | None = None, person: dict | None = None,
                          rewrite=None) -> str:
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


# --- seeing and forgetting facts. Card engine only until Mem0 lands. ----------------

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
    fact = next((f for f in facts if str(f["id"]) == fact_id), None)
    if fact is None:
        return False
    if not await store.delete_fact(tenant_id, fact_id):
        return False
    from app.companion import memory_search
    await memory_search.drop_facts(tenant_id, person["id"], [fact_id])  # its own search piece, always
    # Before the next reply, not in the background, and each step on its own so one failure does not
    # skip the next:
    #   1. every character stops reading its own lines from before this moment (one small write),
    #   2. the cleanup is put on hold-and-queue: until it has finished, replies for this person get the
    #      card only (no "Earlier today", no "Recent days", no old-chat search),
    #   3. the person's words leave their saved messages (no marker).
    # The rest (diary lines, recaps, reworded search pieces) is the background cleanup's.
    from app.companion import alerts, memory_forget
    problems: list[str] = []
    for step, work in (("cutoff", lambda: store.set_read_after(tenant_id, person["id"])),
                       ("hold", lambda: memory_forget.hold(tenant_id, companion_id, person["id"], fact["text"]))):
        try:
            await work()
        except Exception as exc:
            problems.append(f"{step}:{type(exc).__name__}")
    quote = fact.get("quote") or ""
    try:
        erased = await store.erase_words(tenant_id, person["id"], quote)
        logger.info("companion memory: owner delete erased the words from %d message(s), %d search piece(s)",
                    erased["messages"], erased["pieces"])
        if quote.strip() and not erased["messages"]:
            problems.append("words:not_found")      # the fact had a receipt, yet no saved message holds it
        if erased["capped"]:
            problems.append("words:more_chat_than_checked")
    except Exception as exc:
        problems.append(f"words:{type(exc).__name__}")
    if problems:  # the fact row is gone either way; the cleanup below still runs
        logger.error("companion memory: owner delete left the saved chat unclean (%s)", ", ".join(problems))
        await alerts.alert(tenant_id, "companion_memory_delete_incomplete",
                           "An owner deleted a memory, but the saved chat could not be fully cleaned. The "
                           "words may still be in the chat history.", dedupe=False)
    _forget_everywhere(tenant_id, companion_id, person["id"], fact["text"])
    return True


async def list_diary(tenant_id: str, companion_id: str, external_user_id: str) -> dict:
    """The owner's Diary tab: this character's "earlier today" note and its diary lines about the
    person (newest first, the 90 days kept). Empty for an unknown person or a Level 1 character."""
    from app.companion import memory_card, store
    from app.companion.memory_sweep import DIARY_KEEP

    person = await store.find_end_user(tenant_id, external_user_id)
    if not person:
        return {"today": None, "days": []}
    today = await memory_card.person_today(tenant_id, person["id"])   # the person's own day, not the server's
    since = (today - DIARY_KEEP - timedelta(days=1)).isoformat()
    recap = await store.get_recap(tenant_id, companion_id, person["id"])
    rows = await store.diary_since(tenant_id, companion_id, person["id"], since)
    return {"today": {"day": recap["day"], "text": recap["text"]} if recap else None,
            "days": [{"day": str(r["day"])[:10], "text": r["text"]} for r in rows]}


async def forget_diary_day(tenant_id: str, companion_id: str, external_user_id: str, day: str) -> bool:
    """The owner deletes one diary line; its search piece goes with it. False if there was none."""
    from app.companion import store

    person = await store.find_end_user(tenant_id, external_user_id)
    if not person or not await store.delete_diary(tenant_id, companion_id, person["id"], day):
        return False
    await store.delete_chunks(tenant_id, person["id"], companion_id=companion_id, kind="diary", source_keys=[day])
    return True


async def forget_recap(tenant_id: str, companion_id: str, external_user_id: str) -> bool:
    """The owner deletes the "earlier today" note. False if there was none."""
    from app.companion import store

    person = await store.find_end_user(tenant_id, external_user_id)
    if not person or not await store.get_recap(tenant_id, companion_id, person["id"]):
        return False
    await store.clear_recap(tenant_id, companion_id, person["id"])
    return True


_cleanups: set = set()  # strong refs to running cleanups


def _forget_everywhere(tenant_id: str, companion_id: str, end_user_id: str, text: str) -> None:
    """The owner deleted a fact: the same 'forget that' cleanup runs in the background (search
    pieces, diary lines, recaps). Never fails the delete."""
    import asyncio
    import logging

    from app.companion import memory_forget

    async def run():
        try:
            await memory_forget.forget_or_queue(tenant_id, companion_id, end_user_id, [text])
        except Exception as exc:
            logging.getLogger(__name__).warning("companion memory: owner forget cleanup failed (%s)",
                                                type(exc).__name__)

    try:
        task = asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        return
    _cleanups.add(task)
    task.add_done_callback(_cleanups.discard)
