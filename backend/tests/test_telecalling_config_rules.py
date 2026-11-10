"""GET / PATCH /api/v1/settings/telecalling-config with per-channel rules (channel_rules)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role

URL = "/api/v1/settings/telecalling-config"
ROWS = ("whatsapp", "instagram", "facebook", "telegram", "meta_form", "other", "upload")

# Legacy config: the pre-per-channel shape that existing tenants still have stored.
LEGACY = {"enabled": True, "segments": ["B"], "assignment_mode": "push", "shift_mode": "common"}


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": "tenant-1", "role": "owner", "user_id": "user-1", "permissions": [],
        }
        self.cfg = dict(LEGACY)
        self.get_cfg = patch("app.routes.app_settings.get_telecalling_config", side_effect=lambda tid: dict(self.cfg))
        self.save = patch("app.routes.app_settings.save_telecalling_config")
        self.get_cfg.start()
        self.save_mock = self.save.start()

    def tearDown(self):
        patch.stopall()
        app.dependency_overrides.clear()

    def saved(self) -> dict:
        self.save_mock.assert_called_once()
        return self.save_mock.call_args.args[1]


class GetTelecallingConfigTests(_Base):
    def test_always_returns_all_seven_rows_derived_from_legacy_config(self):
        res = self.client.get(URL)

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(set(body["channel_rules"]), set(ROWS))
        self.assertEqual(body["channel_rules"]["whatsapp"], {"enabled": True, "mode": "auto", "segments": ["B"]})
        # Marketplace enquiries were always assigned, even when Cold.
        self.assertEqual(body["channel_rules"]["other"]["segments"], ["A", "B", "C"])
        self.assertEqual(body["channel_rules"]["upload"], {"enabled": True, "mode": "auto"})
        # Legacy keys stay in the response for old readers.
        self.assertEqual(body["segments"], ["B"])
        self.assertEqual(body["assignment_mode"], "push")

    def test_legacy_pull_mode_maps_to_pull_on_every_row(self):
        self.cfg = {**LEGACY, "assignment_mode": "pull"}

        body = self.client.get(URL).json()

        self.assertTrue(all(body["channel_rules"][r]["mode"] == "pull" for r in ROWS))

    def test_stored_channel_rules_are_returned_over_the_legacy_default(self):
        self.cfg = {**LEGACY, "channel_rules": {"instagram": {"enabled": False, "mode": "available", "segments": ["C"]}}}

        body = self.client.get(URL).json()

        self.assertEqual(body["channel_rules"]["instagram"], {"enabled": False, "mode": "available", "segments": ["C"]})
        self.assertEqual(body["channel_rules"]["facebook"]["mode"], "auto")


class PatchTelecallingConfigValidationTests(_Base):
    def test_unknown_row_is_a_400_and_nothing_is_saved(self):
        res = self.client.patch(URL, json={"channel_rules": {"linkedin": {"enabled": True, "mode": "auto", "segments": ["A"]}}})

        self.assertEqual(res.status_code, 400)
        self.assertIn("linkedin", res.json()["detail"])
        self.save_mock.assert_not_called()

    def test_invalid_mode_is_a_400(self):
        res = self.client.patch(URL, json={"channel_rules": {"whatsapp": {"enabled": True, "mode": "round-robin", "segments": ["A"]}}})

        self.assertEqual(res.status_code, 400)
        self.assertIn("invalid mode", res.json()["detail"])
        self.save_mock.assert_not_called()

    def test_invalid_segment_is_a_400(self):
        res = self.client.patch(URL, json={"channel_rules": {"whatsapp": {"enabled": True, "mode": "auto", "segments": ["D"]}}})

        self.assertEqual(res.status_code, 400)
        self.save_mock.assert_not_called()

    def test_missing_enabled_is_a_400(self):
        res = self.client.patch(URL, json={"channel_rules": {"whatsapp": {"mode": "auto", "segments": ["A"]}}})

        self.assertEqual(res.status_code, 400)
        self.save_mock.assert_not_called()

    def test_legacy_fields_are_still_validated(self):
        res = self.client.patch(URL, json={"segments": ["Z"]})

        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid segments", res.json()["detail"])


class PatchTelecallingConfigRulesTests(_Base):
    def test_patch_merges_given_rows_over_the_stored_rules_and_derives_legacy_fields(self):
        self.cfg = {**LEGACY, "channel_rules": {"telegram": {"enabled": True, "mode": "pull", "segments": ["A"]}}}

        res = self.client.patch(URL, json={"channel_rules": {
            "whatsapp": {"enabled": True, "mode": "pull", "segments": ["C"]},
        }})

        self.assertEqual(res.status_code, 200)
        saved = self.saved()
        rules = saved["channel_rules"]
        self.assertEqual(set(rules), set(ROWS))
        self.assertEqual(rules["whatsapp"], {"enabled": True, "mode": "pull", "segments": ["C"]})
        # Rows not sent keep what was stored before.
        self.assertEqual(rules["telegram"], {"enabled": True, "mode": "pull", "segments": ["A"]})
        # Other rows are still enabled on their legacy defaults (B, and A-C for "other"), so the union is A-C.
        self.assertEqual(saved["segments"], ["A", "B", "C"])
        self.assertEqual(saved["assignment_mode"], "push")

    def test_assignment_mode_and_segments_sent_with_channel_rules_are_overridden(self):
        res = self.client.patch(URL, json={
            "assignment_mode": "push",
            "segments": ["A"],
            "channel_rules": {
                "whatsapp": {"enabled": True, "mode": "pull", "segments": ["B"]},
                "instagram": {"enabled": False, "mode": "auto", "segments": ["A"]},
                "facebook": {"enabled": False, "mode": "auto", "segments": []},
                "telegram": {"enabled": False, "mode": "auto", "segments": []},
                "meta_form": {"enabled": False, "mode": "auto", "segments": []},
                "other": {"enabled": False, "mode": "auto", "segments": []},
                "upload": {"enabled": True, "mode": "pull"},
            },
        })

        self.assertEqual(res.status_code, 200)
        saved = self.saved()
        # Every enabled row is pull, so the derived legacy mode is pull; the sent "push" loses.
        self.assertEqual(saved["assignment_mode"], "pull")
        self.assertEqual(saved["segments"], ["B"])

    def test_upload_row_ignores_segments_sent_with_it(self):
        res = self.client.patch(URL, json={"channel_rules": {"upload": {"enabled": True, "mode": "available", "segments": ["A"]}}})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.saved()["channel_rules"]["upload"], {"enabled": True, "mode": "available"})

    def test_patch_response_matches_what_was_saved(self):
        res = self.client.patch(URL, json={"channel_rules": {"other": {"enabled": True, "mode": "auto", "segments": ["A"]}}})

        self.assertEqual(res.json()["channel_rules"], self.saved()["channel_rules"])
        self.assertEqual(res.json()["channel_rules"]["other"]["segments"], ["A"])


if __name__ == "__main__":
    unittest.main()
