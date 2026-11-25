# Lyftr AI Chatbot

A full-stack LLM chatbot with multi-turn conversation memory, automatic API-key failover, response caching, persistent session storage, and per-message inference metadata.

**Tech Stack:** React (Vite), FastAPI, SQLite, LiteLLM, Google Gemini, Docker and nginx.

The API and UI follow the requirements defined in `CONTRACT.md` (sections 3–6).

```text
/backend    FastAPI application, tests, Dockerfile
/frontend   React + Vite application, Dockerfile (nginx), vercel.json
/docs       Deployment and demo documentation
docker-compose.yml
Makefile
.env.example
smoke.sh
```

## 1. Live URLs

- **Frontend:** https://lyftr-ai-chatbot-taupe.vercel.app
- **Backend API:** https://lyftr-ai-chatbot-production-4c45c2ec.up.railway.app
- **Backend Health:** https://lyftr-ai-chatbot-production-4c45c2ec.up.railway.app/health
- **GitHub Repository:** https://github.com/GoelAnshul24/lyftr-ai-chatbot
- **Demo Video:** https://www.loom.com/share/640a58f6840143e5870b7ceac2a96d94

Deployment instructions are available in [`docs/DEPLOY.md`](docs/DEPLOY.md).

---

## 2. Run locally: with Docker and without

### With Docker

Copy the example environment configuration:

```bash
cp .env.example .env
```

Add your Gemini API keys to `.env`:

```env
LLM_API_KEYS=your_key_1,your_key_2
```

Then start the complete application:

```bash
make up
```

Services:

- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- Health endpoint: http://localhost:8000/health

Useful commands:

```bash
make up
make down
make logs
make test
```

Without `make`, Docker Compose can be used directly:

```bash
docker compose up --build -d
docker compose down
```

For the local Docker environment, SQLite uses the named `app-data` volume mounted at `/data`.

```env
DATABASE_URL=sqlite:////data/app.db
```

This allows conversation history to survive backend container restarts.

### Without Docker

#### Backend

```bash
cd backend
python -m venv venv
```

Linux/macOS:

```bash
source venv/bin/activate
```

Windows PowerShell:

```powershell
venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create the backend environment configuration and start FastAPI:

```bash
cp ../.env.example .env
uvicorn app.main:app --port 8000
```

Run backend tests with:

```bash
python -m pytest
```

The test suite mocks external LLM calls and does not require real API calls.

#### Frontend

Open another terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at:

```text
http://localhost:3000
```

By default it communicates with:

```text
http://localhost:8000
```

A different backend can be configured at build time using `VITE_API_URL`.

### Environment Variables

| Variable | Purpose |
|---|---|
| `LLM_API_KEYS` | Comma-separated Gemini API keys |
| `DATABASE_URL` | SQLite database location |
| `ALLOWED_ORIGINS` | Allowed frontend origins for CORS |
| `ENABLE_FAILURE_SIMULATION` | Enables controlled failover testing |
| `LLM_MODEL` | LiteLLM model identifier |
| `DEFAULT_SYSTEM_PROMPT` | Default chatbot system prompt |
| `LLM_TIMEOUT` | Per-key LLM request timeout |
| `PORT` | Backend service port |
| `VITE_API_URL` | Backend URL used by the frontend |

Real API keys are never stored in `.env.example` or committed to the repository.

---

## 3. Design decisions: key fallback, caching, SQLite session storage

### Key fallback

The backend creates an ordered API-key pool from `LLM_API_KEYS`.

LiteLLM Router handles model requests and allows the application to move to the next configured key when a provider request fails.

The API response includes:

- `key_id`
- `fallback_attempts`
- model information
- latency
- input tokens
- output tokens

For example, if `key_1` receives a simulated HTTP 429 error, the request can fall back to `key_2`.

If every configured provider is unavailable, the backend returns:

```json
{
  "detail": "all providers unavailable"
}
```

with HTTP status `503`.

Failed requests are not stored as successful conversation exchanges.

### Failure simulation

When:

```env
ENABLE_FAILURE_SIMULATION=true
```

the application supports the `X-Simulate-Failure` header for controlled testing.

Examples:

```text
key_1=429
```

simulates a rate-limit failure for the first key.

```text
*=429
```

simulates failure across all configured keys.

This makes failover behavior reproducible without intentionally exhausting real provider quotas.

### Caching

The application uses LiteLLM's in-memory caching.

When an identical conversation request is already cached, the response source is displayed as:

```text
LLM_CACHE
```

instead of:

```text
LIVE_INFERENCE
```

Cache hits avoid an unnecessary provider request and normally have significantly lower latency.

The cache is held in process memory and is cleared when the backend process restarts.

### SQLite session storage

Conversation history is stored using SQLite.

Each chat request loads the existing session history and sends the conversation context together with the new user message to the model.

User and assistant messages are stored only after a successful model response.

This means failed requests such as validation errors or provider failures are not stored as successful exchanges.

The session history endpoint is:

```text
GET /sessions/{session_id}/messages
```

---

## 4. Verification: how to see failover, cache hits and per-message token usage

Each assistant response in the frontend displays:

- response source (`LIVE_INFERENCE` or `LLM_CACHE`)
- model
- server-side latency
- input tokens
- output tokens
- API key identifier
- fallback attempts

### Cache Hit

Send a message in a new session and then send the same initial request in another new session.

A cached response displays:

```text
LLM_CACHE
```

and typically returns with much lower latency.

### API-Key Failover

Select:

```text
key_1=429
```

from the **Simulate failure** control and send a message.

The successful response should show:

```text
key: key_2
fallback attempts: 1
```

### All Providers Unavailable

Select:

```text
*=429
```

and send a message.

The frontend displays a readable `503 Service Unavailable` error rather than crashing.

### Token Usage

Every successful assistant response displays input and output token usage for that individual request.

Later conversation turns generally contain more input tokens because previous conversation history is included.

### API Verification

Health:

```bash
curl http://localhost:8000/health
```

Normal chat:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"s-1","message":"What is the capital of France?"}'
```

Failover:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: key_1=429" \
  -d '{"session_id":"s-2","message":"What is the capital of Germany?"}'
```

All providers unavailable:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: *=429" \
  -d '{"session_id":"s-3","message":"This request should fail."}'
```

Session history:

```bash
curl http://localhost:8000/sessions/s-1/messages
```

### Automated Verification

Run:

```bash
./smoke.sh <backend-url>
```

for post-deployment checks.

Backend tests can be run using:

```bash
make test
```

or:

```bash
cd backend
python -m pytest
```

The automated test suite covers key fallback, caching, multi-turn conversations, session isolation, error handling and API behavior.

---

## 5. Setup Used: your editor and AI tools (Claude Code, Gemini)

- **Development environment:** Desktop development environment, terminal, Git and GitHub
- **AI development assistance:** Claude Code was used during development for implementation assistance, debugging and testing
- **LLM integration:** Google Gemini (`gemini/gemini-3.5-flash-lite`) through LiteLLM
- **Backend:** Python, FastAPI, SQLite and LiteLLM
- **Frontend:** React 19 and Vite
- **Deployment:** Railway and Vercel
- **Containerization:** Docker, Docker Compose and nginx

All application behavior was verified through automated backend tests, live API checks and browser-based end-to-end testing.

---

## 6. Bonus features

- Optional system prompt configurable per session
- Multi-turn conversation memory
- LiteLLM response caching
- Automatic API-key failover
- Failure-simulation controls for demonstrating failover behavior
- Per-response source badge (`LIVE_INFERENCE` / `LLM_CACHE`)
- Per-request latency and token usage
- API-key and fallback-attempt metadata
- SQLite-backed session history
- Graceful JSON error handling
- Dockerized frontend and backend
- Non-root backend container user
- Docker health checks
- Post-deployment `smoke.sh` verification script
- Deployment documentation and demo script
- Automated backend test coverage

---

## Project Structure

```text
lyftr-ai-chatbot/
├── backend/
│   ├── app/
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   ├── Dockerfile
│   ├── package.json
│   └── vercel.json
├── docs/
│   ├── DEPLOY.md
│   └── DEMO_SCRIPT.md
├── .env.example
├── .gitignore
├── CONTRACT.md
├── docker-compose.yml
├── Makefile
├── smoke.sh
└── README.md
```

## Security

Real Gemini API keys are provided only through environment variables.

`.env` files containing secrets are excluded from Git tracking through `.gitignore`, while `.env.example` contains placeholder values only.

The application avoids exposing provider credentials in API responses or application logs.

---

**Lyftr AI Full-Stack Assignment — Anshul Goel**
