#!/usr/bin/env bash
# Post-deploy smoke test for the backend API (CONTRACT.md sections 3 and 4).
# Usage:  ./smoke.sh https://your-backend-url        (or: BASE_URL=... ./smoke.sh)
# Needs only bash + curl. Makes ~5 real LLM calls. Exit code is non-zero if any check fails.
BASE_URL="${1:-${BASE_URL:-http://localhost:8000}}"
BASE_URL="${BASE_URL%/}"
RUN="$(date +%s)-$RANDOM"
PASS=0
FAIL=0
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

ok()  { PASS=$((PASS + 1)); printf 'PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL  %s\n        -> %s\n' "$1" "$2"; }

# req METHOD PATH [JSON_BODY] [EXTRA_HEADER]  ->  sets CODE and BODY
req() {
  local method="$1" path="$2" data="${3-}" hdr="${4-}"
  local args=(-sS -m 90 -o "$TMP" -w '%{http_code}' -X "$method" "$BASE_URL$path")
  [ -n "$data" ] && args+=(-H 'Content-Type: application/json' --data-binary "$data")
  [ -n "$hdr" ] && args+=(-H "$hdr")
  CODE="$(curl "${args[@]}" 2>/dev/null)" || CODE=000
  BODY="$(cat "$TMP")"
}

# field NAME  ->  value of "NAME" in $BODY (string, number, null, true/false)
field() {
  # every alternative is non-empty, so null/true/false/numbers/strings are all extracted correctly
  printf '%s' "$BODY" | sed -n "s/.*\"$1\":\(\"[^\"]*\"\|null\|true\|false\|[0-9][0-9]*\).*/\1/p" | head -1 | tr -d '"'
}

chat_body() { printf '{"session_id":"%s","message":"%s"}' "$1" "$2"; }

echo "Smoke test against: $BASE_URL  (run id $RUN)"
echo

# 1. /health
req GET /health
KEYS="$(field keys_configured)"
if [ "$CODE" = 200 ] && [ "$(field status)" = ok ] && [ "${KEYS:-0}" -ge 2 ] 2>/dev/null && [ "$(field cache_enabled)" = true ]; then
  ok "1  GET /health -> 200, status ok, keys_configured=$KEYS, cache_enabled=true"
else
  bad "1  GET /health" "HTTP $CODE: $BODY"
fi

# 2. first chat (live)
MSG="Smoke test $RUN - what is the capital of France? Answer in one short sentence."
S1="smoke-$RUN-a"
req POST /chat "$(chat_body "$S1" "$MSG")"
REPLY1="$(field reply)"
LAT1="$(field latency_ms)"
SRC="$(field resolution_source)"
if [ "$CODE" = 200 ] && [ "$SRC" = LIVE_INFERENCE ] && [ -n "$REPLY1" ] \
   && [[ "$(field key_id)" == key_* ]] && [[ "$(field input_tokens)" =~ ^[0-9]+$ ]] && [[ "$(field output_tokens)" =~ ^[0-9]+$ ]]; then
  ok "2  POST /chat -> 200 LIVE_INFERENCE via $(field key_id), ${LAT1} ms, tokens in=$(field input_tokens) out=$(field output_tokens)"
else
  bad "2  POST /chat (first message)" "HTTP $CODE: $BODY"
fi

# 3. same message, new session -> cache hit
S2="smoke-$RUN-b"
req POST /chat "$(chat_body "$S2" "$MSG")"
LAT2="$(field latency_ms)"
if [ "$CODE" = 200 ] && [ "$(field resolution_source)" = LLM_CACHE ] && [ "$(field reply)" = "$REPLY1" ] \
   && [ "$(field key_id)" = null ] && [ "$(field fallback_attempts)" = 0 ]; then
  ok "3  same message, new session -> LLM_CACHE, identical reply, key_id null, fallback_attempts 0"
else
  bad "3  cache hit" "HTTP $CODE: $BODY"
fi
if [[ "$LAT1" =~ ^[0-9]+$ ]] && [[ "$LAT2" =~ ^[0-9]+$ ]] && [ "$LAT2" -lt "$LAT1" ]; then
  ok "3b cache hit faster than live (${LAT2} ms < ${LAT1} ms)"
else
  bad "3b cache hit faster than live" "live=${LAT1} ms, cache=${LAT2} ms"
fi

# 4. failover: key_1=429 -> served by key_2
S3="smoke-$RUN-c"
req POST /chat "$(chat_body "$S3" "Smoke $RUN - name one primary colour in one word.")" 'X-Simulate-Failure: key_1=429'
if [ "$CODE" = 200 ] && [ "$(field key_id)" = key_2 ] && [ "$(field fallback_attempts)" = 1 ] \
   && [ "$(field resolution_source)" = LIVE_INFERENCE ] && [ -n "$(field reply)" ]; then
  ok "4  X-Simulate-Failure: key_1=429 -> 200 served by key_2, fallback_attempts 1"
else
  bad "4  failover (is ENABLE_FAILURE_SIMULATION=true?)" "HTTP $CODE: $BODY"
fi

# 5. all keys fail -> 503, nothing stored
S4="smoke-$RUN-d"
req POST /chat "$(chat_body "$S4" "Smoke $RUN - this must not be stored.")" 'X-Simulate-Failure: *=429'
if [ "$CODE" = 503 ] && [ "$(field detail)" = "all providers unavailable" ]; then
  ok "5  X-Simulate-Failure: *=429 -> 503 {\"detail\":\"all providers unavailable\"}"
else
  bad "5  all keys fail" "HTTP $CODE: $BODY"
fi
req GET "/sessions/$S4/messages"
if [ "$CODE" = 404 ] && [ "$(field detail)" = "session not found" ]; then
  ok "5b the failed request was not stored (history -> 404 session not found)"
else
  bad "5b failed request must not be stored" "HTTP $CODE: $BODY"
fi

# 6. history endpoint
req GET "/sessions/$S1/messages"
ROLES="$(printf '%s' "$BODY" | grep -o '"role"' | wc -l | tr -d ' ')"
if [ "$CODE" = 200 ] && [ "$ROLES" = 2 ] && [ "$(field session_id)" = "$S1" ] \
   && printf '%s' "$BODY" | grep -q '"role":"user"' && printf '%s' "$BODY" | grep -q '"role":"assistant"' \
   && printf '%s' "$BODY" | grep -q '"resolution_source"' && printf '%s' "$BODY" | grep -q '"input_tokens"' \
   && printf '%s' "$BODY" | grep -q '"output_tokens"' && ! printf '%s' "$BODY" | grep -q '"role":"system"'; then
  ok "6  GET /sessions/{id}/messages -> 200, user + assistant (with metadata), no system prompt"
else
  bad "6  history" "HTTP $CODE: $BODY"
fi

# 7. validation
req POST /chat "$(chat_body "smoke-$RUN-e" "   ")"
if [ "$CODE" = 422 ] && printf '%s' "$BODY" | grep -q '"detail"'; then
  ok "7  whitespace-only message -> 422 with detail"
else
  bad "7  422 (whitespace-only message)" "HTTP $CODE: $BODY"
fi
req POST /chat '{not json'
if [ "$CODE" = 422 ] && printf '%s' "$BODY" | grep -q '"detail"'; then
  ok "7b malformed JSON -> 422 with detail"
else
  bad "7b 422 (malformed JSON)" "HTTP $CODE: $BODY"
fi

echo
echo "Result: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
