import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class CreateClientEntitlementsChecks(unittest.TestCase):
    """
    Static/source-text checks for the create_client -> entitlements wiring.
    No Supabase client is instantiated here; these assertions just verify the
    route source contains the expected contracts (mirrors the pattern used in
    test_logic_contracts_static.py).
    """

    def setUp(self):
        self.source = read("backend/app/routes/operator.py")

    def test_only_one_setting_keys_definition_exists(self):
        matches = re.findall(r"^_SETTING_KEYS\s*[:=]", self.source, flags=re.MULTILINE)
        self.assertEqual(len(matches), 1, "Expected exactly one module-level _SETTING_KEYS definition")

    def test_ai_credential_health_uses_gemini_key(self):
        client_config_idx = self.source.index("def client_config(")
        next_route_idx = self.source.index("\n@router.", client_config_idx + 1)
        client_config_body = self.source[client_config_idx:next_route_idx]
        self.assertIn('"ai": cred_status(["gemini_api_key"])', client_config_body)
        for removed in ("sarvam_api_key", "groq_api_key", "openai_api_key"):
            self.assertNotIn(removed, client_config_body)

    def test_tenant_insert_carries_contact_fields(self):
        self.assertIn('"business_type": payload.business_type', self.source)
        self.assertIn('"contact_name": payload.contact_name', self.source)
        self.assertIn('"contact_phone": payload.contact_phone', self.source)
        self.assertIn('"billing_region": payload.billing_region', self.source)

    def test_migration_adds_contact_columns(self):
        migration = read("backend/supabase/migrations/125_tenant_contact_columns.sql")
        for column in ("business_type", "contact_name", "contact_phone", "billing_region"):
            self.assertRegex(migration, rf"add column if not exists {column} text")

    def test_create_client_no_longer_inserts_a_subscription_row(self):
        """
        Migration 128: new tenants start gated (no tenant_subscriptions row
        at all) until they submit a cart via the client-facing Subscriptions
        page and an admin approves it — create_client must not pre-assign a
        plan or seed entitlements/usage counters anymore.
        """
        create_client_idx = self.source.index("def create_client(")
        next_route_idx = self.source.index("\n@router.", create_client_idx + 1)
        create_client_body = self.source[create_client_idx:next_route_idx]
        self.assertNotIn('db.table("tenant_subscriptions").insert(', create_client_body)
        self.assertNotIn("resolve_entitlements(db, tenant_id)", create_client_body)
        self.assertNotIn('db.table("tenant_usage_counters").insert(', create_client_body)

    def test_create_client_does_not_return_undefined_mrr(self):
        """
        Regression guard: create_client used to `return {..., "mrr": mrr}`
        with `mrr` never assigned anywhere in the function — a NameError on
        every successful client creation (masked in the browser as a CORS
        failure, since the crash response carries no CORS headers). Since
        migration 128 stopped auto-assigning a plan at creation, there is no
        mrr to report here at all.
        """
        create_client_idx = self.source.index("def create_client(")
        next_route_idx = self.source.index("\n@router.", create_client_idx + 1)
        create_client_body = self.source[create_client_idx:next_route_idx]
        self.assertNotIn('"mrr"', create_client_body)
        self.assertIn('return {"tenant_id": tenant_id, "user_id": user_id}', create_client_body)

    def test_cleanup_on_failure_deletes_orphaned_auth_user(self):
        self.assertIn("except Exception as e:", self.source)
        self.assertIn("db.auth.admin.delete_user(user_id)", self.source)
        self.assertIn('detail="Client setup failed; user account cleaned up."', self.source)


if __name__ == "__main__":
    unittest.main()
