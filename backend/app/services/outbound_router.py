import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase
from app.services.number_health import broadcast_cap, can_broadcast, portfolio_limit
from app.services.numbers_pool import get_unlocked_number_ids

logger = logging.getLogger(__name__)

# Re-read the pool every N sends so a mid-broadcast failover (or a pause) is
# picked up without a DB round-trip per message.
_REFRESH_EVERY = 5

# Meta's customer service window: a user who messaged a number in the last 24h
# can be sent to from that number without it counting toward the limit.
_WINDOW = timedelta(hours=24)

# Broadcasts stop at 90% of Meta's limit. The limit also covers templates sent
# from outside Anril (WhatsApp Manager, other tools on the same business), which
# Anril can't see -- the last 10% is room for those. App triggers never stop.
BROADCAST_SHARE_OF_LIMIT = 0.9


def recipient_key(phone: str) -> str:
    """One form per person, so "+919876543210", "919876543210" and
    "98765 43210" count once -- Meta counts unique people. Same rule as the
    broadcast normaliser: digits only, a bare 10-digit number is Indian."""
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return "+" + digits if digits else ""


@dataclass
class Usage:
    """Meta's measure of the limit, from template_send_log: unique people sent
    to outside their 24h window, over the moving 24 hours.
    first_sent_at = the oldest counted send still inside it (when a slot frees)."""
    per_number: dict[str, int] = field(default_factory=dict)
    total: int = 0
    first_sent_at: datetime | None = None


def load_usage(db, tenant_id: str) -> Usage:
    rows = db.rpc("messaging_limit_usage", {"p_tenant": tenant_id}).execute().data or []
    usage = Usage()
    for r in rows:
        if r.get("phone_number_id"):
            usage.per_number[r["phone_number_id"]] = r.get("recipients") or 0
        else:
            usage.total = r.get("recipients") or 0
            if r.get("first_sent_at"):
                usage.first_sent_at = datetime.fromisoformat(str(r["first_sent_at"]).replace("Z", "+00:00"))
    return usage


def _eligible(rows: list[dict], sent_now: dict[str, int], unlocked_ids: set[str], usage: Usage) -> list[dict]:
    """Numbers that may broadcast now and are under their cap, primary first,
    then green before unrated/yellow, then least used."""
    now = datetime.now(timezone.utc)
    # Meta's limit belongs to the business portfolio and every number shares
    # it (Meta reports the same value on each), so usage is the business total
    # -- per-number caps alone would let a second number broadcast past it.
    limit = portfolio_limit(rows)
    pool_used = usage.total + sum(sent_now.values())
    if limit is None or pool_used >= int(limit * BROADCAST_SHARE_OF_LIMIT):
        return []
    out = []
    for r in rows:
        if not can_broadcast(r, now, unlocked_ids):
            continue
        used = usage.per_number.get(r["id"], 0) + sent_now.get(r["id"], 0)
        cap = broadcast_cap(r, now)
        if used >= cap:
            continue
        out.append((r, used / cap))

    def _key(item: tuple[dict, float]) -> tuple:
        r, ratio = item
        return (0 if r.get("role") == "primary" else 1, 0 if r.get("quality_rating") == "green" else 1, ratio)

    return [r for r, _ in sorted(out, key=_key)]


def _load_rows(db, tenant_id: str) -> list[dict]:
    return (
        db.table("phone_numbers")
        .select("*")
        .eq("tenant_id", tenant_id)
        .neq("status", "archived")
        .execute()
        .data
        or []
    )


async def get_best_number(tenant_id: str) -> dict | None:
    db = get_supabase()
    rows = _eligible(_load_rows(db, tenant_id), {}, get_unlocked_number_ids(db, tenant_id), load_usage(db, tenant_id))
    if not rows:
        logger.warning(f"No number can broadcast right now for tenant {tenant_id}")
        return None
    return rows[0]


class SenderPicker:
    """Chooses the sender for each broadcast message. Counts each send
    against the caps as it goes, and re-reads the pool every few sends so a
    failover mid-broadcast moves the rest to the new primary."""

    def __init__(self, tenant_id: str, job: str | None = None):
        self.tenant_id = tenant_id
        # job="reach": Reach campaigns, which follow the number picked for them in
        # WhatsApp > Numbers (services/number_jobs.py). Other senders use the whole pool.
        self.job = job
        self._db = get_supabase()
        self._rows: list[dict] = []
        self._unlocked: set[str] = set()
        self._usage = Usage()
        self._sent_since_refresh: dict[str, int] = {}
        self._calls = 0
        self.used_numbers: list[str] = []

    def _refresh(self) -> None:
        self._rows = _load_rows(self._db, self.tenant_id)
        self._unlocked = get_unlocked_number_ids(self._db, self.tenant_id)
        if self.job == "reach":
            from app.services.number_jobs import reach_pin
            pin = reach_pin(self._db, self.tenant_id, self._rows, datetime.now(timezone.utc), self._unlocked)
            if pin:
                self._rows = [pin]
        self._usage = load_usage(self._db, self.tenant_id)
        self._sent_since_refresh = {}

    def next(self, prefer_meta_id: str | None = None) -> dict | None:
        """The sender for the next message. prefer_meta_id (the number a lead
        already chats with) wins when that number may send."""
        if self._calls % _REFRESH_EVERY == 0:
            self._refresh()
        self._calls += 1
        rows = _eligible(self._rows, self._sent_since_refresh, self._unlocked, self._usage)
        if not rows:
            # Counts may be stale-high or a standby may just have been promoted.
            self._refresh()
            rows = _eligible(self._rows, {}, self._unlocked, self._usage)
        if prefer_meta_id:
            preferred = next((r for r in rows if r.get("meta_phone_number_id") == prefer_meta_id), None)
            if preferred:
                return preferred
        return rows[0] if rows else None

    async def record_sent(self, number: dict) -> None:
        """Track a send locally until the next refresh (counted as if outside
        the window -- the safe side). The real count is written by
        meta_cloud.send_template_message (count_template_send)."""
        self._sent_since_refresh[number["id"]] = self._sent_since_refresh.get(number["id"], 0) + 1
        if number.get("number") and number["number"] not in self.used_numbers:
            self.used_numbers.append(number["number"])

    def numbers_used_label(self) -> str | None:
        return ", ".join(self.used_numbers) or None


def reply_number_for(db, tenant_id: str, last_inbound_phone_number_id: str | None) -> str | None:
    """The number a staff reply should go from: the one the customer last wrote to, when it is
    still one of this business's numbers. WhatsApp's 24-hour window is per number, and a reply
    from another number opens a separate chat on the customer's phone. None = the primary
    (meta_cloud falls back to meta_phone_number_id) -- for someone who never wrote in, or whose
    number was removed. Checked against this tenant's own rows, so it can never pick another
    business's number."""
    if not last_inbound_phone_number_id:
        return None
    try:
        rows = (
            db.table("phone_numbers").select("id")
            .eq("tenant_id", tenant_id)
            .eq("meta_phone_number_id", last_inbound_phone_number_id)
            .neq("status", "archived")
            .limit(1).execute().data or []
        )
    except Exception as e:
        logger.warning(f"reply_number_for: could not read numbers for tenant {tenant_id}: {e}")
        return None
    return last_inbound_phone_number_id if rows else None


def _window_open(db, tenant_id: str, meta_phone_number_id: str, to_number: str) -> bool:
    """Did this person message this same number in the last 24 hours? Meta's
    window is per business number, so a chat with another of our numbers
    doesn't open it. Unknown -> closed (count it: the safe side)."""
    key = recipient_key(to_number)
    rows = (
        db.table("leads").select("last_inbound_at,last_inbound_phone_number_id")
        .eq("tenant_id", tenant_id).in_("phone", list({key, key.lstrip("+"), to_number})).limit(1).execute().data or []
    )
    if not rows or not rows[0].get("last_inbound_at"):
        return False
    if rows[0].get("last_inbound_phone_number_id") != meta_phone_number_id:
        return False
    last = datetime.fromisoformat(str(rows[0]["last_inbound_at"]).replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - last < _WINDOW


def count_template_send(meta_phone_number_id: str, tenant_id: str | None, to_number: str,
                        meta_message_id: str | None = None) -> None:
    """Log a template Meta counts toward the limit: one sent to someone whose
    24h window with this number is closed. Best-effort -- a failed count must
    never fail a send that already happened."""
    try:
        db = get_supabase()
        q = db.table("phone_numbers").select("id,tenant_id").eq("meta_phone_number_id", meta_phone_number_id)
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        rows = q.limit(1).execute().data or []
        if not rows:
            return
        number = rows[0]
        if _window_open(db, number["tenant_id"], meta_phone_number_id, to_number):
            return
        db.table("template_send_log").insert({
            "tenant_id": number["tenant_id"],
            "phone_number_id": number["id"],
            "recipient": recipient_key(to_number) or to_number,
            # Lets a "failed" delivery status remove it again (Meta counts delivered only).
            "meta_message_id": meta_message_id,
        }).execute()
    except Exception as e:
        logger.warning(f"count_template_send failed for {meta_phone_number_id}: {e}")


async def prune_send_log() -> None:
    """Daily: drop log rows that can no longer count (older than 2 days)."""
    db = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    db.table("template_send_log").delete().lt("sent_at", cutoff).execute()
