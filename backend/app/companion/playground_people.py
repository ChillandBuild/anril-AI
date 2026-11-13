"""Playground test customers: the owner chats as a pretend customer of their own app.

Each dashboard login has "You" (external id "owner-test:<login id>", as before) plus up to
MAX_TEST_PEOPLE named test customers ("owner-test:<login id>:t<6 random chars>", display name = what the
owner typed, any language). They are ordinary people to the engine, so memory treats them exactly like
real customers: the after-N-messages refresh, the 02:00 sweep and the diary all include them.
The "owner-test:" prefix keeps the old guards: the public API refuses such ids (keys.valid_user_id) and
the Overview counts skip them (store.TEST_PERSON_PATTERN).

Example: the owner adds a test customer named "Meena" -> "owner-test:4b1e...:tx3k9qa", chats as Meena,
clicks Save now, and finds Meena with a "Playground" tag on the Memories page.
"""
import secrets
import string

from app.companion import engine, store
from app.companion.keys import OWNER_TEST_PREFIX

MAX_TEST_PEOPLE = 10   # named test customers per login per business; "You" is not counted
YOU_NAME = "You"
_SUFFIX_CHARS = string.ascii_lowercase + string.digits


class PersonError(Exception):
    """Shown to the owner as is."""
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def you_id(login_id: str) -> str:
    return f"{OWNER_TEST_PREFIX}{login_id}"


def is_own(external_user_id: str, login_id: str) -> bool:
    """True for this login's "You" or one of its test customers. Another login's test people and
    real customers are never this login's to chat as, save early, start over or delete."""
    you = you_id(login_id)
    return external_user_id == you or external_user_id.startswith(you + ":")


def _row(external_user_id: str, name: str | None, login_id: str) -> dict:
    is_you = external_user_id == you_id(login_id)
    return {"external_user_id": external_user_id, "name": YOU_NAME if is_you else (name or ""), "is_you": is_you}


async def list_people(tenant_id: str, login_id: str) -> list[dict]:
    """"You" first, then the test customers, oldest first."""
    rows = await store.list_test_people(tenant_id, you_id(login_id) + ":")
    return [_row(you_id(login_id), None, login_id)] + [
        _row(r["external_user_id"], r.get("display_name"), login_id) for r in rows]


async def create(tenant_id: str, login_id: str, name: str) -> dict:
    name = " ".join(name.split())
    if not 1 <= len(name) <= 40:
        raise PersonError(422, "Give the test customer a name of 1 to 40 characters")
    existing = await store.list_test_people(tenant_id, you_id(login_id) + ":")
    if len(existing) >= MAX_TEST_PEOPLE:
        raise PersonError(409, f"You can have {MAX_TEST_PEOPLE} test customers. Delete one to add another.")
    external_user_id = f"{you_id(login_id)}:t{''.join(secrets.choice(_SUFFIX_CHARS) for _ in range(6))}"
    await store.find_or_create_end_user(tenant_id, external_user_id, display_name=name)
    return _row(external_user_id, name, login_id)


async def require_usable(tenant_id: str, login_id: str, external_user_id: str) -> None:
    """For chat / memory / save: "You" always; a test customer only while it exists (not deleted)."""
    if not is_own(external_user_id, login_id):
        raise PersonError(404, "Test customer not found")
    if external_user_id == you_id(login_id):
        return
    person = await store.find_end_user(tenant_id, external_user_id)
    if not person or person.get("forgotten_at"):
        raise PersonError(404, "That test customer was deleted")


async def delete(tenant_id: str, login_id: str, external_user_id: str) -> dict:
    """Chats with every character and every memory gone; the test customer leaves the list."""
    if external_user_id == you_id(login_id):
        raise PersonError(400, "\"You\" can't be deleted. Use Start over instead.")
    await require_usable(tenant_id, login_id, external_user_id)
    person = await store.find_end_user(tenant_id, external_user_id)
    await engine.forget_person(tenant_id, external_user_id)
    return person


async def start_over(tenant_id: str, login_id: str, external_user_id: str) -> dict:
    """Same test customer, same id and name, with no chats and no memories: the next chat is a first visit."""
    await require_usable(tenant_id, login_id, external_user_id)
    person = await store.find_end_user(tenant_id, external_user_id)
    if person:   # "You" before its first chat has no row yet: nothing to wipe
        await engine.forget_person(tenant_id, external_user_id)
        await store.revive_end_user(tenant_id, person["id"], person.get("display_name"))
    return _row(external_user_id, (person or {}).get("display_name"), login_id)
