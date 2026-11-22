"""Client connector read tools: knowledge, teaching, brain, automation, handover, AI-reply settings,
catalogue. Per tool: it shows the signed-in client's data, never the other client's, no secret, and
makes no write. The database is a fake; the live one is never touched."""
import inspect
import sys
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.client_mcp import tools_read_ai as t
from app.client_mcp import wrapper
from app.config_dynamic import _CACHE
from app.db import supabase as supabase_db
from app.services.brain import headline
from tests.fake_supabase import FakeSupabase

A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DOC_A = "d0000000-0000-0000-0000-00000000000a"
DOC_B = "d0000000-0000-0000-0000-00000000000b"
ITEM_A = "e0000000-0000-0000-0000-00000000000a"
ITEM_B = "e0000000-0000-0000-0000-00000000000b"
TPL_A = "f0000000-0000-0000-0000-00000000000a"
TPL_B = "f0000000-0000-0000-0000-00000000000b"
LEAD_A = "11111111-1111-1111-1111-11111111111a"
LEAD_B = "11111111-1111-1111-1111-11111111111b"
# Strings that must never reach Claude.
SECRETS = ("SECRET-TOKEN-A", "sk-live-jina-A", "meta-catalog-token-A", "storage/path/secret.pdf", "SECRET-ROW-B")
NOW = "2026-11-20T10:00:00+00:00"


class ReadOnlyDb:
    """The fake database behind the same wall the connector uses: any write, RPC, storage or auth
    call is recorded in `attempts` AND raised (some handlers swallow errors, so the record matters)."""
    WRITES = {"insert", "update", "upsert", "delete"}

    def __init__(self, inner: FakeSupabase):
        self.inner, self.attempts = inner, []

    def table(self, name):
        outer = self
        real = self.inner.table(name)

        class Guard:
            def __getattr__(self, attr):
                if attr in outer.WRITES:
                    outer.attempts.append(f"{name}.{attr}")
                    raise supabase_db.ReadOnlyViolation(f"{attr} on {name}")
                return getattr(real, attr)
        return Guard()

    from_ = table

    def rpc(self, fn, *args, **kwargs):
        self.attempts.append(f"rpc.{fn}")
        raise supabase_db.ReadOnlyViolation(f"rpc {fn}")

    def __getattr__(self, attr):  # storage, auth, ...
        self.attempts.append(attr)
        raise supabase_db.ReadOnlyViolation(attr)


def seeded() -> FakeSupabase:
    """Two clients, each with one of everything. Client B's rows carry SECRET-ROW-B."""
    db = FakeSupabase()
    for tenant, name in ((A, "Shop A"), (B, "Shop B")):
        db.add("tenants", id=tenant, name=name, status="active")
    # knowledge
    db.add("knowledge_documents", id=DOC_A, tenant_id=A, name="Prices A", file_type="pdf", size_bytes=10, status="indexed",
           full_text="FACTS-A " + "x" * 40_000, storage_path="storage/path/secret.pdf")
    db.add("knowledge_documents", id=DOC_B, tenant_id=B, name="SECRET-ROW-B doc", file_type="pdf", size_bytes=10,
           status="indexed", full_text="SECRET-ROW-B text")
    db.add("knowledge_chunks", tenant_id=A, document_id=DOC_A)
    db.add("app_settings", tenant_id=A, key="jina_api_key", value="sk-live-jina-A", is_secret=True)
    db.add("app_settings", tenant_id=A, key="business_description", value="WHO WE ARE\nA shop")
    # teaching
    db.add("ai_teach_items", tenant_id=A, kind="answer", prompt="Open Sunday?", reply="Yes 10 to 5", match_key="open sunday",
           times_taught=1, source="manual", updated_at=NOW)
    db.add("ai_teach_items", tenant_id=B, kind="answer", prompt="SECRET-ROW-B?", reply="SECRET-ROW-B", match_key="x",
           times_taught=1, source="manual", updated_at=NOW)
    db.add("ai_offers", tenant_id=A, title="Diwali 10 percent", details="all week", starts_on="2026-01-01",
           ends_on="2099-12-31", deleted_at=None)
    db.add("ai_offers", tenant_id=B, title="SECRET-ROW-B offer", details="", starts_on="2026-01-01",
           ends_on="2099-12-31", deleted_at=None)
    # business details (app_settings blob) and tenant seed
    db.add("app_settings", tenant_id=A, key="business_details", value='{"legal_name": "Shop A Pvt", "gstin": "33ABCDE1234F1Z5"}')
    db.add("app_settings", tenant_id=B, key="business_details", value='{"legal_name": "SECRET-ROW-B Pvt"}')
    # templates, rules, sends
    db.add("message_templates", id=TPL_A, tenant_id=A, name="diwali_a", status="APPROVED", category="MARKETING", language="en",
           body_text="Hi {{1}}", buttons=[])
    db.add("message_templates", id=TPL_B, tenant_id=B, name="SECRET-ROW-B tpl", status="APPROVED", category="MARKETING",
           language="en", body_text="SECRET-ROW-B", buttons=[])
    db.add("auto_message_rules", tenant_id=A, event="interested", template_id=TPL_A, variables=[], enabled=True)
    db.add("auto_message_rules", tenant_id=B, event="interested", template_id=TPL_B, variables=[], enabled=True)
    db.add("auto_message_events", tenant_id=A, key="vip", label="VIP", description=None)
    db.add("auto_message_events", tenant_id=B, key="secretb", label="SECRET-ROW-B", description=None)
    db.add("app_settings", tenant_id=A, key="auto_messages_ingest_token", value="SECRET-TOKEN-A", is_secret=True)
    db.add("app_settings", tenant_id=B, key="auto_messages_ingest_token", value="SECRET-ROW-B", is_secret=True)
    db.add("auto_message_sends", tenant_id=A, lead_id=None, phone="919000000001", name="Priya", event="interested",
           source="website", template_id=TPL_A, status="sent", reason=None, send_at=NOW, sent_at=NOW, created_at=NOW)
    db.add("auto_message_sends", tenant_id=B, lead_id=None, phone="919999999999", name="SECRET-ROW-B", event="interested",
           source="website", template_id=TPL_B, status="sent", reason=None, send_at=NOW, sent_at=NOW, created_at=NOW)
    # handovers
    db.add("leads", id=LEAD_A, tenant_id=A, name="Priya", phone="919000000001")
    db.add("leads", id=LEAD_B, tenant_id=B, name="SECRET-ROW-B", phone="919999999999")
    db.add("chat_handovers", tenant_id=A, lead_id=LEAD_A, assigned_to=None, reason="Customer asked for a person",
           status="pending", opened_at=NOW)
    db.add("chat_handovers", tenant_id=A, lead_id=LEAD_A, assigned_to=None, reason="Customer asked for a person",
           status="resolved", opened_at=NOW, resolved_at="2026-11-20T10:05:00+00:00", resolved_by_name="Karthik")
    db.add("chat_handovers", tenant_id=B, lead_id=LEAD_B, assigned_to=None, reason="SECRET-ROW-B",
           status="pending", opened_at=NOW)
    db.add("chat_handovers", tenant_id=B, lead_id=LEAD_B, assigned_to=None, reason="SECRET-ROW-B",
           status="resolved", opened_at=NOW, resolved_at=NOW, resolved_by_name="SECRET-ROW-B")
    # AI reply settings
    db.add("app_settings", tenant_id=A, key="ai_auto_reply_enabled", value="false")
    db.add("app_settings", tenant_id=A, key="inbox_config", value='{"enabled": true, "segments": ["B"]}')
    db.add("app_settings", tenant_id=B, key="inbox_config", value='{"enabled": true, "segments": ["SECRET-ROW-B"]}')
    # catalogue
    db.add("catalog_items", id=ITEM_A, tenant_id=A, name="Silk saree", item_type="product", description="red", status="ready",
           price_paise=250000, stock_quantity=4, embedding=[0.1], created_at="2026-11-01T00:00:00")
    db.add("catalog_items", id=ITEM_B, tenant_id=B, name="SECRET-ROW-B saree", item_type="product", status="ready",
           price_paise=1, stock_quantity=1, created_at="2026-11-02T00:00:00")
    db.add("catalog_item_variants", tenant_id=A, catalog_item_id=ITEM_A, size="M", colour="Red", stock_quantity=0, sort_order=1)
    db.add("catalog_item_variants", tenant_id=B, catalog_item_id=ITEM_B, size="SECRET-ROW-B", colour="x", stock_quantity=1, sort_order=1)
    db.add("stock_movements", tenant_id=A, catalog_item_id=ITEM_A, delta=-1, quantity_after=4, reason="sale", note="n")
    db.add("stock_movements", tenant_id=B, catalog_item_id=ITEM_B, delta=-1, quantity_after=0, reason="SECRET-ROW-B", note="n")
    db.add("catalog_media", id="m1", tenant_id=A, catalog_item_id=ITEM_A, storage_path="storage/path/secret.pdf", label="front")
    db.add("catalog_variant_groups", tenant_id=A, name="Sarees", item_type="product")
    db.add("catalog_variant_groups", tenant_id=B, name="SECRET-ROW-B group", item_type="product")
    db.add("app_settings", tenant_id=A, key="meta_catalog_id", value="cat-1")
    db.add("app_settings", tenant_id=A, key="meta_catalog_access_token", value="meta-catalog-token-A", is_secret=True)
    return db


def run(fn, db, tenant=A, **kwargs):
    """Run a tool's plain function as `tenant`'s owner against `db`, behind the read-only wall."""
    guarded = ReadOnlyDb(db)
    _CACHE.clear()
    headline.clear_cache()
    with ExitStack() as stack:
        stack.enter_context(patch.object(supabase_db, "get_supabase", return_value=guarded))
        for name, module in list(sys.modules.items()):
            if name.startswith("app.") and getattr(module, "get_supabase", None) is not None \
                    and module.get_supabase is not guarded and getattr(module.get_supabase, "__module__", "") == "app.db.supabase":
                stack.enter_context(patch.object(module, "get_supabase", return_value=guarded))
        stack.enter_context(wrapper.acting_as(tenant, user_id="owner-a" if tenant == A else "owner-b"))
        result = fn(**kwargs)
    assert guarded.attempts == [], f"{fn.__name__} tried to write: {guarded.attempts}"
    return result


def clean(result) -> str:
    """The tool's answer as text, proven free of secrets and of client B's rows."""
    text = str(result)
    for secret in SECRETS:
        assert secret not in text, f"{secret} leaked"
    return text


NO_ARGS = [t.knowledge_base, t.teach_and_offers, t.business_profile, t.anril_brain, t.auto_message_rules,
           t.auto_messages_sent, t.handover_queue, t.ai_reply_settings, t.catalogue]


def test_all_eleven_tools_registered_and_none_takes_a_client():
    names = {"knowledge_base", "knowledge_document_text", "teach_and_offers", "business_profile", "anril_brain",
             "auto_message_rules", "auto_messages_sent", "handover_queue", "ai_reply_settings", "catalogue", "catalogue_item"}
    assert names <= set(wrapper.REGISTRY)
    for name in names:
        params = set(inspect.signature(wrapper.REGISTRY[name].fn).parameters)
        assert not params & {"tenant", "tenant_id", "client", "client_id", "user_id"}, name


@pytest.mark.parametrize("fn", NO_ARGS)
def test_tools_show_only_the_signed_in_clients_rows_and_no_secrets(fn):
    db = seeded()
    result = run(fn, db, tenant=A)
    clean(result)
    # B signed in sees B's rows, never A's.
    other = str(run(fn, db, tenant=B))
    assert "Shop A" not in other and "Silk saree" not in other and "Priya" not in other and "Prices A" not in other


# ── (a) the signed-in client's data is really there ───────────────────────────

def test_knowledge_base_lists_own_files_without_storage_path():
    out = run(t.knowledge_base, seeded())
    assert [d["name"] for d in out["documents"]] == ["Prices A"]
    assert out["documents"][0]["searchable"] is True
    assert "storage_path" not in out["documents"][0] and len(out["readiness"]) == 8
    clean(out)


def test_knowledge_document_text_truncates_and_checks_owner():
    db = seeded()
    out = run(t.knowledge_document_text, db, document_id=DOC_A)
    assert out["text"].startswith("FACTS-A") and len(out["text"]) == t.MAX_DOC_TEXT and "note" in out
    assert out["total_chars"] > t.MAX_DOC_TEXT
    with pytest.raises(ToolError):  # B's document id, asked as A
        run(t.knowledge_document_text, db, document_id=DOC_B)
    with pytest.raises(ToolError):
        run(t.knowledge_document_text, db, document_id="not-an-id")


def test_teach_and_offers_content():
    out = run(t.teach_and_offers, seeded())
    assert [i["prompt"] for i in out["taught"]] == ["Open Sunday?"]
    assert [o["title"] for o in out["offers"]] == ["Diwali 10 percent"]


def test_business_profile_content():
    out = run(t.business_profile, seeded())
    assert out["legal_name"] == "Shop A Pvt" and out["gstin"] == "33ABCDE1234F1Z5"
    assert run(t.business_profile, seeded(), tenant=B)["legal_name"] == "SECRET-ROW-B Pvt"


def test_anril_brain_content():
    out = run(t.anril_brain, seeded())
    assert {"headline", "waiting", "inputs", "handovers", "status"} <= set(out["brain"])
    assert "count" in out["waiting_count"]


def test_auto_message_rules_hide_the_intake_link_and_use_own_rules():
    out = run(t.auto_message_rules, seeded())
    assert [r["event"] for r in out["rules"]] == ["interested"]
    assert out["rules"][0]["has_sent"] is True and out["rules"][0]["template_approved"] is True
    assert out["setup"]["intake_link_created"] is True and "ingest" not in str(out["setup"]).lower().replace("intake", "")
    assert [e["key"] for e in out["events"]["custom"]] == ["vip"]
    assert [x["name"] for x in out["templates"]] == ["diwali_a"]
    clean(out)


def test_auto_messages_sent_content_and_limit():
    db = seeded()
    out = run(t.auto_messages_sent, db, limit=10)
    assert [r["event"] for r in out["send_log"]["sends"]] == ["interested"]
    assert out["sent_last_7_days"]["total"] >= 0
    for bad in (0, 51):
        with pytest.raises(ToolError):
            run(t.auto_messages_sent, db, limit=bad)


def test_handover_queue_content():
    out = run(t.handover_queue, seeded())
    assert [h["lead_id"] for h in out["pending"]] == [LEAD_A] and out["pending_count"] == 1
    assert [h["resolved_by_name"] for h in out["history"]["data"]] == ["Karthik"]


def test_ai_reply_settings_content():
    out = run(t.ai_reply_settings, seeded())
    assert out["ai_replies_on"] is False and out["inbox_config"]["segments"] == ["B"]
    assert any(s["key"] == "whatsapp" for s in out["sources"])


def test_catalogue_lists_own_items_and_searches():
    db = seeded()
    out = run(t.catalogue, db)
    assert [i["name"] for i in out["items"]] == ["Silk saree"]
    assert "embedding" not in out["items"][0] and out["items"][0]["out_variants"] == ["Red M"]
    assert [g["name"] for g in out["variant_groups"]] == ["Sarees"]
    assert out["meta_catalogue"]["connected"] is True
    assert run(t.catalogue, db, search="silk")["items"] and not run(t.catalogue, db, search="zzz")["items"]
    with pytest.raises(ToolError):
        run(t.catalogue, db, limit=99)
    clean(out)


def test_catalogue_item_content_and_ownership():
    db = seeded()
    out = run(t.catalogue_item, db, item_id=ITEM_A)
    assert out["item"]["name"] == "Silk saree"
    assert out["photos"] == {"count": 1, "labels": ["front"]}
    assert [v["size"] for v in out["variants"]["variants"]] == ["M"]
    assert [m["reason"] for m in out["stock_movements"]] == ["sale"]
    clean(out)
    with pytest.raises(ToolError):  # B's item, asked as A
        run(t.catalogue_item, db, item_id=ITEM_B)
    with pytest.raises(ToolError):
        run(t.catalogue_item, db, item_id="nope")
