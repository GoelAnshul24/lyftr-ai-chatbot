# Demo video script (target 2:45, limit 3:00)

Screen recording with your voice. Use the **deployed** frontend and backend URLs the whole time.

## Before you record (5 minutes, not on camera)

- [ ] Backend is up: `curl <backend>/health` returns 200 with `keys_configured: 2` (and `ENABLE_FAILURE_SIMULATION=true` is set on the deployed backend).
- [ ] Open three browser tabs: (1) the Vercel frontend, (2) `<backend>/health`, (3) a blank tab you will use for the history URL.
- [ ] Have a terminal open with the backend URL exported: `B=https://YOUR-BACKEND-URL` (for the optional curl shot).
- [ ] Pick a question nobody has asked on this backend yet (the cache is shared by everyone), e.g. *"What is the capital of Australia? Answer in one short sentence."* If you rehearsed with it, use a different one on camera.
- [ ] Zoom the browser to about 110-125% so the small metadata text is readable. Close other tabs and notifications.
- [ ] Do not show the Railway/Vercel variables pages (they contain your keys).

## Timed script

| Time | On screen | Say (suggested) |
|---|---|---|
| **0:00-0:12** | Frontend tab, empty chat | "This is my LLM chatbot for the Lyftr assignment: React on Vercel, FastAPI on Railway, SQLite on a persistent volume, and LiteLLM with Gemini behind it. Everything you see is the deployed version." |
| **0:12-0:27** | Switch to the `/health` tab, refresh | "Endpoint one: `GET /health`. It returns 200 only when the database is reachable and at least two API keys are loaded. Here: status ok, two keys configured, cache enabled." |
| **0:27-0:55** | Frontend: type the fresh question, press Enter | "Endpoint two: `POST /chat`, through the UI. Notice the loading state, then the answer. Next to it: a blue LIVE_INFERENCE badge because this went to the model, the model name, the latency in milliseconds, and the input and output tokens for this request only. Below, the key that answered and zero fallback attempts." |
| **0:55-1:20** | Reload the page, send the **same** question | "Reloading starts a new session. I send the same question again. Now the badge is green, LLM_CACHE: identical reply, the same token counts, no key used, and latency drops from about a second to a few milliseconds. That is LiteLLM's built-in cache; the key is the model plus the full message list." |
| **1:20-1:50** | Send a follow-up: *"What did I just ask you?"* Then open the history tab: `<backend>/sessions/<session id>/messages` (the id is shown top right in the UI) | "Multi-turn memory: it knows my earlier question, because the backend loads this session's history from SQLite and sends it with every request. Endpoint three: `GET /sessions/{id}/messages` shows the stored history, oldest first, with the metadata on each assistant message and no system prompt." |
| **1:50-2:20** | Back to the UI. Dropdown: `key_1=429`. Send a **new** question. | "Now failover. This dropdown sends the `X-Simulate-Failure` header; the backend honors it because simulation is enabled. I make key_1 return a 429. LiteLLM's Router falls back to the next key, so the user still gets a real answer: the key line shows key_2 and one fallback attempt." |
| **2:20-2:42** | Dropdown: `*=429`. Send a message. | "Now every key fails. The app shows a readable error, not a blank screen or a stack trace: 503, all providers unavailable. And this request was not saved to history." |
| **2:42-2:50** | (Optional) terminal: `./smoke.sh $B` scrolling PASS lines, or just the UI | "I also wrote a smoke script that checks all of this against the live URL, plus validation errors. Code, README and tests are in the GitHub repo. Thanks for watching." |

## Optional shots if you finish early (cut these first if you run long)

- 422: send 4001 characters (or use curl with `"message":"   "`) and show the JSON `detail` error.
- `curl -i -X POST $B/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: *=429' -d '{"session_id":"demo","message":"hi"}'` to show the raw 503 body.
- Show `/sessions/<id>/messages` for the 503 session returning 404 "session not found".

## Tips

- Rehearse once; keep each beat short. If a live call is slow, keep talking over the loading dots.
- If Gemini's free quota is exhausted you will get a real 503 even without the dropdown: check `/health` and try again later, or use keys from two different Google projects.
- Upload the video, make the link public, and paste it into the README "Live URLs" table and the submission form.
