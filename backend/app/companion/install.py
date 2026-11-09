"""The copy-paste code the dashboard's Install tab shows for one character.

Nothing secret is in here: the snippets read the key from the business's own environment
variable ANRIL_COMPANION_KEY. Example for Jothidar AI (id 7c1e...):
- html:    the two script tags for their web page (widget in the corner);
- python / node: the server function that signs a user id for the widget;
- curl:    one server-to-server chat call, for apps that draw their own chat screen.
"""
import os

DEFAULT_WIDGET_ORIGIN = "https://www.anrilaitech.com"
DEFAULT_API_BASE = "https://aira-ai-5tfr.onrender.com"


def widget_origin() -> str:
    return (os.environ.get("COMPANION_WIDGET_ORIGIN") or DEFAULT_WIDGET_ORIGIN).rstrip("/")


def api_base() -> str:
    return (os.environ.get("COMPANION_API_BASE") or DEFAULT_API_BASE).rstrip("/")


def install_info(companion: dict) -> dict:
    cid = companion["id"]
    origin, api = widget_origin(), api_base()
    script_url = f"{origin}/companion-widget.js"
    html = f"""<script src="{script_url}" defer></script>
<script>
  // userId, exp and signature come from YOUR server (see the server code). Never put the secret key here.
  window.addEventListener("load", function () {{
    AnrilCompanion.init({{
      companionId: "{cid}",
      userId: CURRENT_USER.id,
      exp: CURRENT_USER.companionExp,
      signature: CURRENT_USER.companionSignature,
      displayName: CURRENT_USER.name,
      // Optional app-run tools: the character can ask your page to run these.
      tools: [],
      onToolCall: async function (call) {{ return {{ error: "not implemented" }}; }},
    }});
  }});
</script>"""
    python = '''import hashlib, hmac, os, time

def companion_signature(user_id: str) -> dict:
    """Call this on YOUR server for the logged-in user; pass the result to the page."""
    key = os.environ["ANRIL_COMPANION_KEY"]          # acs_live_... from the Install tab
    exp = int(time.time()) + 24 * 3600               # valid for 1 day (30 at most)
    signing_key = hashlib.sha256(key.encode()).hexdigest()
    sig = hmac.new(signing_key.encode(), f"{exp}.{user_id}".encode(), hashlib.sha256).hexdigest()
    return {"userId": user_id, "exp": exp, "signature": sig}'''
    node = '''const crypto = require("crypto");

// Call this on YOUR server for the logged-in user; pass the result to the page.
function companionSignature(userId) {
  const key = process.env.ANRIL_COMPANION_KEY;       // acs_live_... from the Install tab
  const exp = Math.floor(Date.now() / 1000) + 24 * 3600;  // 1 day (30 at most)
  const signingKey = crypto.createHash("sha256").update(key).digest("hex");
  const signature = crypto.createHmac("sha256", signingKey).update(`${exp}.${userId}`).digest("hex");
  return { userId, exp, signature };
}'''
    curl = f"""curl -X POST {api}/api/v1/companion/chat \\
  -H "Authorization: Bearer $ANRIL_COMPANION_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{{"companion_id": "{cid}", "user_id": "48213", "message": "Vanakkam!"}}'"""
    return {
        "companion_id": cid,
        "status": companion.get("status"),
        "widget_script_url": script_url,
        "api_base": api,
        "snippets": {"html": html, "python": python, "node": node, "curl": curl},
    }
