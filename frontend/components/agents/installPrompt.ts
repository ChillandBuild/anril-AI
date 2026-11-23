import type { CompanionInstall } from "@/lib/api";

/** Public path of the machine-readable API description (frontend/public). */
export const OPENAPI_PATH = "/anril-agents-api.openapi.yaml";

/**
 * A prompt the owner pastes into their AI coding tool (Cursor, Claude Code...)
 * so it installs the character on their site. Built from GET /{id}/install;
 * holds no secret: the key stays in ANRIL_COMPANION_KEY on their server.
 */
export function installPrompt(info: CompanionInstall, characterName: string): string {
  return [
    `Add the "${characterName}" chat character from Anril Agents to my website.`,
    "",
    "1. Put my Anril Agents secret key in a server environment variable named ANRIL_COMPANION_KEY. Never send it to the browser.",
    "2. Add this server function (pick the one for my backend's language) and call it for the logged-in user:",
    "",
    "Python:",
    "```python",
    info.snippets.python,
    "```",
    "",
    "Node:",
    "```js",
    info.snippets.node,
    "```",
    "",
    "3. Pass its userId, exp and signature to the page, then add this to every page where the chat should show:",
    "```html",
    info.snippets.html,
    "```",
    "",
    "Replace CURRENT_USER with however my app exposes the logged-in user. Show me the changes before applying them.",
  ].join("\n");
}

/**
 * The own-app prompt: the business keeps its own app and chat screen, and its backend calls
 * POST /chat for every message. Works for any backend (Django, Express, Laravel, Rails...).
 * Holds no secret; the character id and the API address are filled in.
 * Example: appPrompt(info, "Maya") -> "...Agent id (companion_id): `c1`...".
 */
export function appPrompt(info: CompanionInstall, characterName: string): string {
  const api = `${info.api_base}/api/v1/companion`;
  return `You are connecting this project to "${characterName}", an AI agent on Anril Agents. The agent answers
this app's users. This project keeps its own app, chat screen and design; only the source of the replies
changes. Work through the steps in order and ask me before changing anything this prompt does not describe.

## Values

- API base: \`${api}\`
- Agent id (\`companion_id\`): \`${info.companion_id}\`
- Secret key: ONLY in the backend's environment as \`ANRIL_COMPANION_KEY\` (starts with \`acs_live_\`).
  Never in the mobile app, the web page, git, logs or error messages.
- Machine-readable API description (OpenAPI 3.1): the Install page in Anril links it.

## How it works

\`\`\`
User types in YOUR app
   |
YOUR backend  -- knows who is logged in, which profile is open, and that profile's data
   |  POST /chat   (secret key + user_id + profile_id + app_data + message)
Anril agent   -- answers; keeps a separate memory and history per user + profile
   |
YOUR backend  -- returns text / bubbles / chips / button to YOUR app, shown in YOUR design
\`\`\`

The app never talks to Anril and never holds the key. This is not a raw model API: the agent's persona,
rules, knowledge files, AI model and memory live in Anril. Do NOT send a system prompt, a model name or the
chat history; send only the new message and what you know about the person.

## Step 0: look before you build. Tell me, before writing code:

1. The backend framework and how a request knows the logged-in user.
2. The existing chat screen's API: which endpoint the app calls to send a message and what it returns.
   Keep that endpoint and its response shape, so the app needs as few changes as possible (ideally none).
3. Profiles: can one login hold several people (family members, children, horoscopes, pets)? Which table
   holds them, its primary key, and how a chat request says which profile is selected.
4. The data held per profile that the agent should know (plan, orders, a horoscope...) and the function
   that produces it.
5. Where the app stores chat history today. Keep storing it there; the app shows its own history.

## Step 1: who is talking, about whom (one memory per profile)

| Field | What to send |
|---|---|
| \`user_id\` | The login's primary key, from the authenticated session, never from the request body. |
| \`profile_id\` | The selected profile's primary key (row id). Never its position in a list, never reused. If the app has profiles, ALWAYS send it, including for the user's own profile: sending it on some messages and not others splits one person's memory in two. Omit only if the app has no profiles. |
| \`display_name\` | The logged-in person's name: who the agent talks TO. |
| \`profile_name\` | The selected profile's name: who the data is ABOUT. |

Anril keeps one memory and history per (\`user_id\`, \`profile_id\`). Example: login 48213 (Ravi) has profiles
101 Ravi, 102 Meena, 103 Arjun. A chat on 102 never sees what was said on 103. Send only the selected
profile's data; if the user asks about another profile, the reply's tag is usually \`need_details\` and the
agent asks them to open it, so show your profile switcher.
Ids: letters, digits and \`_ . @ : -\`, starting with a letter or digit; user_id up to 128, profile_id up to 64.

## Step 2: app_data, with EVERY message

\`app_data\` = what you know about the selected profile: a JSON object or text, up to 12,000 characters.
Build it fresh from your database for every message; Anril never stores it, so a corrected record is used
from the next message. Never include passwords, payment details or another profile's data.
If the data is a horoscope, send your chart engine's JSON as it is (Anril's chart check reads the keys
\`overview\` with \`lagnam\`/\`rasi\`, \`planets\`, \`navamsa\`, \`dasa\`, \`gocharam\`).

## Step 3: the call

\`POST ${api}/chat\` with headers \`Authorization: Bearer $ANRIL_COMPANION_KEY\` and
\`Content-Type: application/json\`. JSON in, JSON out, no streaming. Unknown fields are refused (422).

\`\`\`json
{
  "companion_id": "${info.companion_id}",
  "user_id": "48213",
  "profile_id": "102",
  "display_name": "Ravi",
  "profile_name": "Meena",
  "timezone": "Asia/Kolkata",
  "reply_language": "English",
  "message": "What should Meena focus on this month?",
  "app_data": { "...": "the selected profile's data" },
  "reply_format": {
    "buttons": [{"id": "expert", "when": "the question needs a human expert", "handoff": true}],
    "questions_left": 3
  }
}
\`\`\`

- \`message\`: 1-4,000 characters. \`timezone\`: the user's IANA zone; always send it.
- \`reply_language\`: the language the user reads in the app (their app-language setting), e.g. \`"English"\`,
  \`"ta"\` or \`"Tamil, written in Tamil script"\`. The bubbles and chips come in it, whatever language the
  question was typed in. Leave it out to use the agent's own language. Up to 60 characters; an unknown language is a 422.
- \`reply_format\` (recommended): the reply comes as short bubbles plus follow-ups.
  - \`buttons\`: up to 6 of YOUR action buttons. \`id\`: lowercase letters, digits, \`_\`, up to 32, not one of
    \`counted ask_back greeting off_topic need_details none failed handoff\`. \`when\`: when to show it (up to 200
    characters). At most one has \`"handoff": true\`: the one shown when the agent hands over to a human.
  - \`questions_left\`: how many questions this user may still ask (0 = no follow-up chips; leave it out if
    you don't limit questions).
- A reply takes about 4-10 seconds. Use a 60-second HTTP timeout and check the server's worker timeout
  (gunicorn, nginx, PHP max_execution_time) allows it. Show a typing indicator in the app.

Reference function, in Python (port it to this project's language):

\`\`\`python
${info.snippets.chat_python}
\`\`\`

## Step 4: the reply, mapped onto your UI

\`\`\`json
{"status": "done", "text": "First part...\\n\\nSecond part...",
 "bubbles": ["First part...", "Second part..."], "chips": ["A follow-up?", "Another one?"],
 "button": null, "tag": "counted", "mood": "calm", "basis": "primary",
 "sources": [{"document": "Guide", "page_from": 12, "page_to": 12}],
 "conversation_id": "...", "message_id": "...", "turn_id": null, "tool_calls": []}
\`\`\`

- \`bubbles\` (1-3): separate chat bubbles. \`text\` = the same joined by a blank line (use it for one bubble
  per reply, or if you sent no reply_format).
- \`chips\` (0 or 2): tappable follow-up questions; tapping one sends it as the next message.
- \`button\`: one of your button ids or null; show that button under the reply.
- \`tag\`: \`counted\` = a real answer (count it against the user's question limit). Anything else
  (\`ask_back\`, \`greeting\`, \`off_topic\`, \`need_details\`, a button id, \`handoff\`, \`failed\`) is not:
  don't count it. \`failed\` = the AI couldn't answer; \`text\` is a polite sorry line.
- \`sources\`: optional "From: Guide, p. 12" line.
- Save the reply into the app's own chat history.

Tools are optional and usually not needed: anything the agent should know goes in app_data. Only if I ask
for tools: send up to 8 \`tools\` (\`[{"name", "description", "parameters"}]\`); a reply with
\`"status": "tool_call"\` lists \`tool_calls\` (\`{"id", "name", "args"}\`); run them on the backend and within 2
minutes \`POST ${api}/chat/continue\` with \`{"user_id", "profile_id", "turn_id", "results": [{"id", "output"}]}\`.

## Step 5: errors

Every error is \`{"error": "<text>", "code": "<code>"}\`. Show a friendly message in the app, never the raw error.

| HTTP | code | What the backend does |
|---|---|---|
| 401 | invalid_key | Key missing, wrong or revoked: config problem, alert the team. |
| 409 | companion_not_live | The agent is switched off: "AI chat is unavailable right now". |
| 404 | companion_not_found | Wrong agent id: config problem. |
| 404 | turn_expired | (tools only) Send the message again as a new /chat. |
| 422 | invalid_user_id, invalid_profile_id, empty_message, tools_invalid | Bug in the request: fix it. |
| 429 | rate_limited | Wait \`Retry-After\` (60 s). Limits: 20 messages/min per user, 600/min per business. |
| 503 | busy | Wait \`Retry-After\` (5 s), retry once, then "Try again in a moment". |
| 503 | companion_not_configured | The business hasn't finished AI setup in Anril. |

Don't log message text or app_data; log the code, user_id, profile_id and timing only.

## Step 6: when a profile or account is deleted

After your own delete commits, tell Anril to forget that person (same key header):
\`POST ${api}/forget\` with \`{"user_id": "48213", "profile_id": "103"}\` for one profile (the others stay), or
\`{"user_id": "48213"}\` for the whole account and every profile under it. Reply \`{"forgotten": true}\`, or
\`false\` if they never chatted (not an error). Its own limit is 600/min per business; 503 busy = retry later.
Calling it twice is safe, so a background retry is fine.

## Step 7: done means

1. On a test login, the existing chat screen sends "Hello" and shows the agent's reply, with no app change
   or only the changes listed in Step 0.
2. Memory is separate per profile: on profile A send "Remember, my pet's name is Bruno." On profile B ask
   "What is my pet's name?": the agent doesn't know. Back on A: "Bruno".
3. app_data is rebuilt per message: change a field of profile A in the database, ask about it, and the
   answer uses the new value.
4. Bubbles, chips and buttons show in the app's own design; a \`counted\` tag decrements the question count
   and other tags don't.
5. The key is only in the backend environment: grep the app source and the built app/bundle for
   \`acs_live_\`: zero hits.
6. Each error code in Step 5 has a handler (unit-test them with a mocked HTTP client).
7. Deleting a test profile calls /forget with its profile_id.

Report what you built, the files changed, and the result of each check.`;
}
