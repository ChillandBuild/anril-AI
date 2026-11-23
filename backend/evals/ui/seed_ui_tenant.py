"""Seed a little sample data into the UI TEST tenant only, so local UI checks have something to act on.

    cd backend && .venv/bin/python -m evals.ui.seed_ui_tenant

Reads the tenant from evals/ui/.test-account.json and refuses any tenant not named "Aira UI Test (Claude)".
Safe to re-run: it skips when the sample leads already exist. Phones are fake (+91 90000 0000x) and the
test tenant has no WhatsApp connected, so nothing can be sent to them.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db.supabase import get_supabase

TEST_NAME = "Aira UI Test (Claude)"
LEADS = [  # name, segment, tags, opted_out, blocked
    ("Revathi M", "A", ["vip", "saree"], False, False),
    ("Karthik S", "B", ["saree"], False, False),
    ("Meena R", "C", ["wholesale"], False, False),
    ("Arjun P", "B", [], True, False),
    ("Priya K", "A", ["vip"], False, True),
]


def main() -> None:
    acct = json.loads((Path(__file__).parent / ".test-account.json").read_text())
    tid = acct["tenant_id"]
    db = get_supabase()
    tenant = db.table("tenants").select("name").eq("id", tid).limit(1).execute().data
    if not tenant or tenant[0]["name"] != TEST_NAME:
        raise SystemExit(f"Refusing: tenant {tid} is not the UI test tenant")
    if db.table("catalog_items").select("id").eq("tenant_id", tid).eq("name", "Silk saree").limit(1).execute().data:
        print("Sample data already there")
        return
    now = datetime.now(timezone.utc)
    ids = []
    for i, (name, seg, tags, opted_out, blocked) in enumerate(LEADS, start=1):
        row = {"tenant_id": tid, "name": name, "phone": f"+9190000000{i:02d}", "source": "whatsapp", "segment": seg,
               "score": {"A": 9, "B": 6, "C": 3}[seg], "opted_out": opted_out,
               "opted_out_at": now.isoformat() if opted_out else None,
               "blocked_at": now.isoformat() if blocked else None,
               "last_inbound_at": (now - timedelta(hours=i * 5)).isoformat()}
        have = db.table("leads").select("id").eq("tenant_id", tid).eq("phone", row["phone"]).limit(1).execute().data
        if have:  # a half-finished earlier run
            ids.append(have[0]["id"])
            continue
        lead = db.table("leads").insert(row).execute().data[0]
        ids.append(lead["id"])
        for t in tags:
            db.table("lead_tags").insert({"tenant_id": tid, "lead_id": lead["id"], "tag": t}).execute()
    item = db.table("catalog_items").insert({"tenant_id": tid, "name": "Silk saree", "price_paise": 450000}).execute().data[0]
    deals = [  # lead index, stage, total, paid
        (0, "awaiting_payment", 450000, 0),
        (1, "awaiting_payment", 900000, 300000),
        (2, "awaiting_payment", 450000, 0),
        (3, "awaiting_payment", 450000, 0),    # said stop: Remind all skips
        (0, "won", 450000, 450000),
    ]
    for n, (li, stage, total, paid) in enumerate(deals, start=1):
        deal = db.table("deals").insert({
            "tenant_id": tid, "lead_id": ids[li], "deal_number": 900 + n, "stage": stage, "source": "manual",
            "channel": "online", "total_paise": total, "won_at": now.isoformat() if stage == "won" else None,
            "payment_method": "cash" if stage == "won" else None,
        }).execute().data[0]
        db.table("deal_items").insert({"tenant_id": tid, "deal_id": deal["id"], "catalog_item_id": item["id"],
                                       "name": "Silk saree", "qty": total // 450000, "unit_price_paise": 450000,
                                       "line_total_paise": total}).execute()
        if paid:
            db.table("deal_payments").insert({"tenant_id": tid, "deal_id": deal["id"], "amount_paise": paid,
                                              "method": "upi", "kind": "full" if paid == total else "advance"}).execute()
    print(f"Seeded {len(LEADS)} leads, 1 item, {len(deals)} orders into the UI test tenant")


if __name__ == "__main__":
    main()
