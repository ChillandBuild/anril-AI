import logging

from pydantic import model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str
    supabase_jwt_secret: str | None = None
    groq_api_key: str | None = None
    sarvam_api_key: str | None = None
    gemini_api_key: str | None = None
    jina_api_key: str | None = None
    telecmi_app_id: str | None = None
    telecmi_user_id: str | None = None
    telecmi_secret: str | None = None
    telecmi_agent_password: str | None = None
    telecmi_callerid: str | None = None
    telecmi_recording_base_url: str | None = None
    public_base_url: str | None = None
    # PE-TM binding (DLT Setup): the telemarketer clients bind their entity to. Same for every client.
    sms_tm_name: str = "SID GROUPS PRIVATE LIMITED"
    sms_tm_id: str = "1702178720558766591"
    # What Meta charges per marketing template message sent in India, in rupees, before GST.
    # One number, used by the Reach confirm step's cost line (services/reach_audience.py). Env: META_MARKETING_RATE_INR.
    meta_marketing_rate_inr: float = 0.8631
    meta_page_token: str | None = None
    meta_verify_token: str | None = None
    meta_ig_user_id: str | None = None
    meta_access_token: str | None = None
    meta_phone_number_id: str | None = None
    meta_app_id: str | None = None
    telegram_bot_token: str | None = None
    instagram_access_token: str | None = None
    instagram_page_id: str | None = None
    facebook_access_token: str | None = None
    facebook_page_id: str | None = None
    meta_app_secret: str | None = None
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    vapid_subject: str | None = None
    # Razorpay OAuth partner app (services/razorpay_oauth.py): one app for every tenant, like Meta's.
    razorpay_oauth_client_id: str | None = None
    razorpay_oauth_client_secret: str | None = None
    razorpay_oauth_redirect_uri: str | None = None  # the frontend's /dashboard/settings/razorpay-callback
    razorpay_oauth_webhook_secret: str | None = None
    razorpay_oauth_mode: str = "live"  # "test" with the Development client
    # Local-run safety (see scripts/dev-backend.sh). Production defaults: scheduler runs,
    # outbound is live. A laptop sets SCHEDULER_ENABLED=false + OUTBOUND_MODE=dry_run so it
    # never runs the 15 jobs against the live DB or messages real people.
    scheduler_enabled: bool = True
    outbound_mode: str = "live"  # "live" | "dry_run"
    outbound_allow_to: str = ""  # comma-separated recipients that still get REAL sends in dry_run
    # Scheduled jobs run on Procrastinate (Postgres queue, SPEC.md). DATABASE_URL is the Supabase
    # session pooler string (port 5432); without it no scheduled job runs.
    database_url: str | None = None
    # Claude Access (read-only admin MCP, docs/specs/anril-admin-mcp.md). Off = the /mcp address
    # does not exist. MCP_OAUTH_CLIENT_ID is the OAuth client registered for Claude in Supabase;
    # when set, tokens from any other client are refused.
    mcp_enabled: bool = False
    mcp_oauth_client_id: str | None = None
    # The address the Claude app uses for the MCP, when it is not the backend's normal one
    # (e.g. https://mcp.anrilaitech.com). Claude shows a connector's icon from the favicon of the
    # address's root domain, so a subdomain of the website shows the Anril icon. MCP only:
    # PUBLIC_BASE_URL stays as it is (webhook addresses registered with Meta depend on it).
    mcp_public_base_url: str | None = None
    # Anril AI: the client connector at /client/mcp (docs/specs/anril-client-mcp.md). Off = that
    # address does not exist. MCP_CLIENT_OAUTH_CLIENT_IDS is a comma-separated list of the OAuth
    # apps allowed to use it (one per approved app, e.g. Claude). The admin app's id is never
    # accepted here, and these ids are never accepted at /mcp.
    mcp_client_enabled: bool = False
    mcp_client_oauth_client_ids: str = ""
    # Which TCP peers may tell us the client's IP through CF-Connecting-IP / X-Forwarded-For
    # (per-IP rate limits: OTP, booking link, QR, website form). Comma-separated CIDRs.
    # Unset = private and loopback ranges, which is where Render's load balancer connects from.
    # "" = trust no one (every limit keys on the socket address). See routes/auto_messages._client_ip.
    trusted_proxy_cidrs: str | None = None

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}

    @model_validator(mode="after")
    def _check_outbound_mode(self) -> "Settings":
        if self.outbound_mode not in ("live", "dry_run"):
            raise ValueError(f"OUTBOUND_MODE must be 'live' or 'dry_run', got {self.outbound_mode!r}")
        return self

    @model_validator(mode="after")
    def _warn_missing_secrets(self) -> "Settings":
        # sarvam_api_key/gemini_api_key/groq_api_key/jina_api_key are per-tenant only
        # (app_settings, configured in the operator console) -- every AI provider has no
        # platform-wide fallback, so those fields are unused at runtime by the AI code
        # paths and are not listed as critical here (see decisions/log.md). meta_app_secret
        # stays critical -- it's still read from here for the Embedded Signup OAuth
        # exchange (one shared Meta app for every tenant), not per-tenant AI billing.
        critical = {
            "meta_app_secret": "Webhook signature verification will reject all inbound",
        }
        for key, impact in critical.items():
            if not getattr(self, key):
                logger.warning("Missing %s — %s", key, impact)
        return self


settings = Settings()
