"""The copy-paste code the dashboard's Install tab shows for one character.

Nothing secret is in here: the snippets read the key from the business's own environment
variable ANRIL_COMPANION_KEY. Example for Jothidar AI (id 7c1e...):
- html:    the two script tags for their web page (widget in the corner);
- python / node: the server function that signs a user id for the widget;
- curl:    one server-to-server chat call, for apps that draw their own chat screen.
- chat_python / chat_node / chat_php: the same /chat call as a ready function, for any backend
  (Django, Flask, Express, Laravel...). The app keeps its own chat screen; one memory per user + profile.
"""
import os

DEFAULT_WIDGET_ORIGIN = "https://www.anrilaitech.com"
DEFAULT_API_BASE = "https://api.anrilaitech.com"   # Render custom domain since 23 Nov 2026; onrender.com still answers


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
  -d '{{"companion_id": "{cid}",
       "user_id": "48213", "profile_id": "102",
       "display_name": "Ravi", "profile_name": "Meena",
       "timezone": "Asia/Kolkata", "reply_language": "English",
       "message": "Hello!",
       "app_data": {{"plan": "Gold"}},
       "reply_format": {{"buttons": [], "questions_left": null}}}}'"""
    chat_python = f'''import os, requests   # pip install requests

ANRIL_CHAT = "{api}/api/v1/companion/chat"
COMPANION_ID = "{cid}"


def ask_anril(user_id, message, profile_id=None, display_name=None, profile_name=None,
              app_data=None, timezone="Asia/Kolkata", questions_left=None, reply_language=None):
    """Call on YOUR server for each message. Returns the reply: text, bubbles, chips, button, tag."""
    body = {{
        "companion_id": COMPANION_ID,
        "user_id": str(user_id),                  # your login's id
        "profile_id": str(profile_id) if profile_id is not None else None,   # the selected profile's row id
        "display_name": display_name,             # who is typing
        "profile_name": profile_name,             # whose profile app_data is about
        "timezone": timezone,
        "reply_language": reply_language,         # e.g. "English" or "ta"; None = the agent's own language
        "message": message,
        "app_data": app_data,                     # that profile's data, every message (never stored)
        "reply_format": {{"buttons": [], "questions_left": questions_left}},
    }}
    body = {{k: v for k, v in body.items() if v is not None}}
    r = requests.post(ANRIL_CHAT, json=body, timeout=60,
                      headers={{"Authorization": "Bearer " + os.environ["ANRIL_COMPANION_KEY"]}})
    data = r.json()
    if r.status_code != 200:   # {{"error", "code"}}: rate_limited, busy, invalid_key...
        raise RuntimeError(f"Anril {{r.status_code}} {{data.get('code')}}")
    return data'''
    chat_node = f'''// Node 18+ (built-in fetch). Call on YOUR server for each message.
const ANRIL_CHAT = "{api}/api/v1/companion/chat";
const COMPANION_ID = "{cid}";

async function askAnril({{ userId, message, profileId, displayName, profileName, appData,
                          timezone = "Asia/Kolkata", questionsLeft = null, replyLanguage }}) {{
  const body = {{
    companion_id: COMPANION_ID,
    user_id: String(userId),                                  // your login's id
    profile_id: profileId == null ? undefined : String(profileId),  // the selected profile's row id
    display_name: displayName,                                // who is typing
    profile_name: profileName,                                // whose profile appData is about
    timezone,
    reply_language: replyLanguage,                            // e.g. "English"; undefined = the agent's own
    message,
    app_data: appData,                                        // that profile's data, every message
    reply_format: {{ buttons: [], questions_left: questionsLeft }},
  }};
  const r = await fetch(ANRIL_CHAT, {{
    method: "POST",
    headers: {{ "Authorization": `Bearer ${{process.env.ANRIL_COMPANION_KEY}}`, "Content-Type": "application/json" }},
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(60000),
  }});
  const data = await r.json();
  if (!r.ok) throw new Error(`Anril ${{r.status}} ${{data.code}}`);   // rate_limited, busy, invalid_key...
  return data;   // text, bubbles, chips, button, tag
}}'''
    chat_php = f'''<?php
// Call on YOUR server for each message (plain PHP or Laravel).
function ask_anril($userId, $message, $profileId = null, $displayName = null, $profileName = null,
                   $appData = null, $timezone = "Asia/Kolkata", $questionsLeft = null,
                   $replyLanguage = null) {{
    $body = array_filter([
        "companion_id" => "{cid}",
        "user_id" => (string) $userId,                                  // your login's id
        "profile_id" => $profileId === null ? null : (string) $profileId,  // the selected profile's row id
        "display_name" => $displayName,                                 // who is typing
        "profile_name" => $profileName,                                 // whose profile $appData is about
        "timezone" => $timezone,
        "reply_language" => $replyLanguage,                             // e.g. "English"; null = the agent's own
        "message" => $message,
        "app_data" => $appData,                                         // that profile's data, every message
        "reply_format" => ["buttons" => [], "questions_left" => $questionsLeft],
    ], fn($v) => $v !== null);
    $ch = curl_init("{api}/api/v1/companion/chat");
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 60,
        CURLOPT_HTTPHEADER => ["Authorization: Bearer " . getenv("ANRIL_COMPANION_KEY"), "Content-Type: application/json"],
        CURLOPT_POSTFIELDS => json_encode($body, JSON_UNESCAPED_UNICODE),
    ]);
    $raw = curl_exec($ch);
    $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    $data = json_decode($raw, true);
    if ($status !== 200) throw new Exception("Anril $status " . ($data["code"] ?? ""));
    return $data;   // text, bubbles, chips, button, tag
}}'''
    return {
        "companion_id": cid,
        "status": companion.get("status"),
        "widget_script_url": script_url,
        "api_base": api,
        "snippets": {"html": html, "python": python, "node": node, "curl": curl,
                     "chat_python": chat_python, "chat_node": chat_node, "chat_php": chat_php},
    }
