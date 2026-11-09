"""Mock Astrotamil site: shows how a business embeds the Anril companion widget.

It plays the business's SERVER (it holds the secret key and signs the user id) and serves one
page that embeds the widget. Standard library only.

    ANRIL_COMPANION_KEY=acs_live_... COMPANION_ID=<character id> python3 demo_server.py
    open http://localhost:8787            (?user=48213 to be someone else)

WIDGET_ORIGIN (default http://localhost:3000) is where companion-widget.js and the chat window
are served: the local frontend, or https://www.anrilaitech.com once deployed. The page also
registers one app-run tool, get_chart, answered with a fixed sample chart.
"""
import hashlib
import hmac
import html
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

KEY = os.environ.get("ANRIL_COMPANION_KEY", "")
COMPANION_ID = os.environ.get("COMPANION_ID", "")
WIDGET_ORIGIN = os.environ.get("WIDGET_ORIGIN", "http://localhost:3000").rstrip("/")
PORT = int(os.environ.get("PORT", "8787"))


def companion_signature(user_id: str) -> dict:
    """The same function the Install tab gives businesses."""
    exp = int(time.time()) + 24 * 3600
    signing_key = hashlib.sha256(KEY.encode()).hexdigest()
    sig = hmac.new(signing_key.encode(), f"{exp}.{user_id}".encode(), hashlib.sha256).hexdigest()
    return {"userId": user_id, "exp": exp, "signature": sig}


GET_CHART = {
    "name": "get_chart",
    "description": "Use when the user gives their birth date, time and place. Returns their chart.",
    "parameters": {"type": "object", "properties": {
        "date": {"type": "string"}, "time": {"type": "string"}, "place": {"type": "string"}}},
}

PAGE = """<!doctype html>
<html lang="ta"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Astrotamil (mock)</title>
<style>
 body{{margin:0;font-family:system-ui,sans-serif;background:#fff8ef;color:#3b2412}}
 header{{background:#7a1f0c;color:#ffe9b3;padding:18px 24px;font-size:22px;font-weight:700}}
 main{{max-width:720px;margin:32px auto;padding:0 16px;line-height:1.6}}
 .card{{background:#fff;border:1px solid #f0d9b5;border-radius:12px;padding:16px 20px;margin:16px 0}}
 small{{color:#8a6a4a}}
</style></head>
<body>
<header>Astrotamil <small style="color:#ffd27a">(mock site for the Anril widget)</small></header>
<main>
 <div class="card"><b>Logged in as:</b> {name} (user id {user_id})<br>
 <small>This page's server signed the user id with the secret key; the browser never sees the key.</small></div>
 <div class="card">Indraiya raasi palan, panchangam, jathagam... <br>
 Click the chat button (bottom right) to talk to the character.</div>
</main>
<script src="{origin}/companion-widget.js"></script>
<script>
 var SIGNED = {signed};
 AnrilCompanion.init({{
   companionId: {companion_id},
   userId: SIGNED.userId, exp: SIGNED.exp, signature: SIGNED.signature,
   displayName: {name_js},
   tools: [{tool}],
   onToolCall: async function (call) {{
     if (call.name === "get_chart") {{
       return {{ lagna: "Kumbham", moon: "Rishabam", nakshatra: "Rohini", dasha: "Guru", input: call.args }};
     }}
     return {{ error: "unknown tool" }};
   }},
   open: true,
 }});
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path != "/":
            self.send_error(404)
            return
        q = parse_qs(url.query)
        user_id = (q.get("user") or ["48213"])[0]
        name = (q.get("name") or ["Karthik"])[0]
        body = PAGE.format(
            origin=html.escape(WIDGET_ORIGIN, quote=True),
            signed=json.dumps(companion_signature(user_id)).replace("<", "\\u003c"),
            companion_id=json.dumps(COMPANION_ID),
            name=html.escape(name), user_id=html.escape(user_id),
            name_js=json.dumps(name).replace("<", "\\u003c"),
            tool=json.dumps(GET_CHART),
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass


if __name__ == "__main__":
    if not KEY.startswith("acs_live_") or not COMPANION_ID:
        raise SystemExit("Set ANRIL_COMPANION_KEY (acs_live_...) and COMPANION_ID first.")
    print(f"Mock Astrotamil on http://localhost:{PORT}  (widget from {WIDGET_ORIGIN})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
