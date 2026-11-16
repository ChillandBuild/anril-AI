"""Who on the team is acting -- for labels that must survive a rename or removal
(handover history, the name on a teammate's chat reply)."""


def actor_name(db, ctx: dict) -> str | None:
    """Display name for whoever is acting. Owners can act without a caller profile,
    so fall back to their tenant_users.full_name."""
    caller_id = ctx.get("caller_id")
    if caller_id:
        try:
            row = db.table("callers").select("name").eq("id", caller_id).limit(1).execute()
            if row.data and row.data[0].get("name"):
                return row.data[0]["name"]
        except Exception:
            pass
    try:
        row = (
            db.table("tenant_users")
            .select("full_name")
            .eq("user_id", ctx["user_id"])
            .eq("tenant_id", ctx["tenant_id"])
            .limit(1)
            .execute()
        )
        if row.data and row.data[0].get("full_name"):
            return row.data[0]["full_name"]
    except Exception:
        pass
    return None


def sender_fields(db, ctx: dict) -> dict:
    """The sent_by_* columns (migration 272) for an outbound message a teammate sent."""
    return {"sent_by_user_id": ctx.get("user_id"), "sent_by_name": actor_name(db, ctx)}
