# Companion widget demo (mock Astrotamil)

A fake business site that embeds the Anril companion widget, so you can try the whole flow on a laptop.

```
browser (localhost:8787)              Anril frontend (localhost:3000)        Anril API (localhost:8000)
mock Astrotamil page ── loads ──► companion-widget.js
  signed user id (from this server) ──► chat window (iframe) ── /widget/chat ──► engine.reply
  onToolCall(get_chart) ◄── postMessage ── tool_call  ◄──────────────────────── status "tool_call"
```

1. In the dashboard, create a secret key for the companion API (the Install tab), and set the character to Live.
2. Run the backend with `make dev-backend` and the frontend with `NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev`.
3. Start the mock site:

```bash
ANRIL_COMPANION_KEY=acs_live_... COMPANION_ID=<character id> python3 sdk/companion-demo/demo_server.py
```

4. Open http://localhost:8787. Add `?user=55555&name=Priya` to chat as someone else.

Demo only, not production code: it signs whatever `?user=` you pass, so a real site must sign only the logged-in user.

The key stays in this terminal. The page only gets the user id, an expiry and the signature.
