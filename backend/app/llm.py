import logging
from dataclasses import dataclass

import litellm
from litellm import Cache, Router
from starlette.concurrency import run_in_threadpool

from .config import Settings

logger = logging.getLogger("app.llm")

# X-Simulate-Failure status -> litellm exception raised for that key
SIM_ERRORS = {
    429: litellm.RateLimitError,
    500: litellm.InternalServerError,
    502: litellm.BadGatewayError,
    503: litellm.ServiceUnavailableError,
}


class AllProvidersUnavailable(Exception):
    pass


@dataclass
class LLMResult:
    reply: str
    resolution_source: str  # LIVE_INFERENCE | LLM_CACHE
    key_id: str | None
    fallback_attempts: int
    input_tokens: int
    output_tokens: int


CACHE_TTL_SECONDS = 24 * 3600  # LiteLLM's in-memory default is only 600 s (10 min)


def setup_cache() -> None:
    # litellm built-in, in-memory cache. Must be set before build_router().
    litellm.cache = Cache(default_in_memory_ttl=CACHE_TTL_SECONDS)


def build_router(settings: Settings) -> Router:
    """One model group per key (key_1, key_2, ...), each with that key's api_key.
    - num_retries=0, disable_cooldowns=True: every request tries key_1 first; no key is "benched".
    - cache_responses + caching_groups: litellm's cache key is the same for every key group,
      so a cached answer is shared no matter which key produced it."""
    # The Router logs provider error text at ERROR level; keep it out of our logs.
    logging.getLogger("LiteLLM Router").setLevel(logging.CRITICAL)
    model_list = [
        {"model_name": kid, "litellm_params": {"model": settings.llm_model, "api_key": key}, "model_info": {"id": kid}}
        for kid, key in zip(settings.key_ids, settings.api_keys)
    ]
    return Router(
        model_list=model_list,
        num_retries=0,
        disable_cooldowns=True,
        timeout=settings.llm_timeout,
        caching_groups=[tuple(settings.key_ids)],
        cache_responses=True,
    )


def warm_up(router: Router, group: str) -> None:
    """The first cache hit lazily imports litellm code (~650 ms). Do it at startup, with no network."""
    try:
        m = [{"role": "user", "content": "__warmup__"}]
        for _ in range(2):
            router.completion(model=group, messages=m, mock_response="ok")
    except Exception as e:
        logger.warning("startup warm-up failed: %s", type(e).__name__)


def parse_failure_header(value: str | None) -> dict[str, int]:
    """'key_1=429,key_2=500' or '*=429' -> {'key_1': 429, ...}. Invalid pairs are ignored."""
    out: dict[str, int] = {}
    for part in (value or "").split(","):
        key, sep, status = part.partition("=")
        key, status = key.strip(), status.strip()
        if sep and key and status.isascii() and status.isdigit() and int(status) in SIM_ERRORS:
            out[key] = int(status)
    return out


async def generate(messages: list[dict], settings: Settings, simulate: dict[str, int], router: Router) -> LLMResult:
    key_ids = settings.key_ids

    # Simulated failures are raised here, BEFORE any real call, for this request only.
    live = []
    for kid in key_ids:
        status = simulate.get(kid, simulate.get("*"))
        if status is None:
            live.append(kid)
        else:
            exc = SIM_ERRORS[status](message=f"simulated {status}", llm_provider="gemini", model=settings.llm_model)
            logger.warning("%s failed: %s (simulated)", kid, type(exc).__name__)
    if not live:
        raise AllProvidersUnavailable()

    # Real keys go through the Router: try live[0]; on any failure it falls back through live[1:] in order.
    primary, rest = live[0], live[1:]
    extra = {"cache": {"no-cache": True}} if simulate else {}  # header present -> skip cache read
    try:
        # Sync completion in a threadpool: litellm writes the cache before returning
        # (acompletion writes it in the background, so an immediate repeat can miss).
        resp = await run_in_threadpool(
            router.completion,
            model=primary,
            messages=messages,
            fallbacks=[{primary: rest}] if rest else None,
            timeout=settings.llm_timeout,
            **extra,
        )
        reply = resp.choices[0].message.content
        if not reply or not reply.strip():
            raise ValueError("empty reply")
    except Exception as e:
        logger.warning("all remaining keys failed: %s", type(e).__name__)  # never the message: it may echo secrets
        raise AllProvidersUnavailable() from None

    hit = bool(resp._hidden_params.get("cache_hit"))
    answered = resp._hidden_params.get("model_id") or primary  # the key group that produced the reply
    return LLMResult(
        reply=reply,
        resolution_source="LLM_CACHE" if hit else "LIVE_INFERENCE",
        key_id=None if hit else answered,
        # every key before the one that answered failed (simulated or real)
        fallback_attempts=0 if hit else key_ids.index(answered),
        input_tokens=int(resp.usage.prompt_tokens),
        output_tokens=int(resp.usage.completion_tokens),
    )
