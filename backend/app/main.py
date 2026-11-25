import logging
import sqlite3
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from . import db, llm
from .config import MIN_KEYS, get_settings
from .schemas import ChatRequest

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = get_settings()
    db.init_db(app.state.settings.db_path)
    llm.setup_cache()
    app.state.router = llm.build_router(app.state.settings)
    if app.state.settings.key_ids:  # with no keys /health reports 503; there is nothing to warm up
        llm.warm_up(app.state.router, app.state.settings.key_ids[0])
    yield


app = FastAPI(lifespan=lifespan)


async def catch_all_errors(request: Request, call_next):
    """Any unexpected error -> JSON 500. Unlike an Exception handler this does not re-raise,
    so uvicorn never prints a traceback. Log only the exception type: never keys or details."""
    try:
        return await call_next(request)
    except Exception as e:
        logger.error("unhandled error: %s", type(e).__name__)
        return JSONResponse({"detail": "internal server error"}, status_code=500)


# Added BEFORE CORS so CORS stays outermost and 500 responses still carry CORS headers.
app.add_middleware(BaseHTTPMiddleware, dispatch=catch_all_errors)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().allowed_origins),
    allow_methods=["*"],
    allow_headers=["Content-Type", "X-Simulate-Failure"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.get("/health")
def health(request: Request):
    s = request.app.state.settings
    try:
        db.check_db(s.db_path)
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail="database unreachable")
    if len(s.api_keys) < MIN_KEYS:  # counts only, never key values
        raise HTTPException(
            status_code=503,
            detail=f"key pool not ready: {len(s.api_keys)} of at least {MIN_KEYS} required keys configured",
        )
    return {"status": "ok", "keys_configured": len(s.api_keys), "cache_enabled": True}


@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: str, request: Request):
    messages = db.get_history(request.app.state.settings.db_path, session_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "messages": messages}


@app.post("/chat")
async def chat(body: ChatRequest, request: Request, x_simulate_failure: str | None = Header(default=None)):
    start = time.perf_counter()
    s = request.app.state.settings

    given_prompt = body.system_prompt if body.system_prompt and body.system_prompt.strip() else None
    stored_prompt, history = await run_in_threadpool(db.load_context, s.db_path, body.session_id)
    system_prompt = given_prompt or stored_prompt or s.default_system_prompt
    messages = (
        [{"role": "system", "content": system_prompt}]
        + [{"role": m["role"], "content": m["content"]} for m in history]
        + [{"role": "user", "content": body.message}]
    )

    simulate = llm.parse_failure_header(x_simulate_failure) if s.enable_failure_simulation else {}
    try:
        result = await llm.generate(messages, s, simulate, request.app.state.router)
    except llm.AllProvidersUnavailable:
        raise HTTPException(status_code=503, detail="all providers unavailable")

    metadata = {
        "resolution_source": result.resolution_source,
        "model": s.llm_model,
        "latency_ms": int(round((time.perf_counter() - start) * 1000)),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "key_id": result.key_id,
        "fallback_attempts": result.fallback_attempts,
    }
    # Only reached after success: the one place messages are saved.
    await run_in_threadpool(
        db.save_exchange, s.db_path, body.session_id, given_prompt, body.message, result.reply, metadata
    )
    return {"session_id": body.session_id, "reply": result.reply, "metadata": metadata}
