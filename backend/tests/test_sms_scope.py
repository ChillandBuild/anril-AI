from app.services import rbac


def test_sms_permissions_only_cover_client_messaging():
    assert {p["key"] for p in rbac.PERMISSION_CATALOG if p["group"] == "SMS"} == {"sms.view", "sms.manage"}


def test_sms_financial_routes_are_not_available():
    from app.main import app
    paths = set(app.openapi()["paths"])
    assert not paths.intersection({
        "/api/v1/sms/recharge", "/api/v1/sms/packs", "/api/v1/sms/payments",
        "/api/v1/sms/ledger", "/webhook/razorpay-sms",
        "/api/v1/operator/sms/stock", "/api/v1/operator/clients/{tenant_id}/sms/credit",
        "/api/v1/operator/clients/{tenant_id}/sms/debit", "/api/v1/operator/clients/{tenant_id}/sms/account",
    })


def test_client_sms_and_operator_connection_routes_remain():
    from app.main import app
    paths = set(app.openapi()["paths"])
    assert {
        "/api/v1/sms/campaigns", "/api/v1/sms/templates", "/api/v1/sms/balance",
        "/api/v1/sms/dlt/entity", "/api/v1/sms/dlt/sender-excel", "/api/v1/sms/dlt/template-excel",
        "/api/v1/sms/otp/send", "/api/v1/sms/otp/verify", "/api/v1/sms/otp/resend",
        "/api/v1/sms/developer/key", "/webhook/bulk9/{tenant_id}",
        "/api/v1/operator/clients/{tenant_id}/sms/key", "/api/v1/operator/clients/{tenant_id}/sms/webhook",
    } <= paths


def test_existing_razorpay_oauth_is_not_removed_with_sms_recharge():
    from app.main import app
    assert "/api/v1/intake/razorpay-oauth-webhook" in set(app.openapi()["paths"])
