# syntax=docker/dockerfile:1

# ---- Stage 1: build the virtualenv (compilers/caches stay in this stage) ----
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /build
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- Stage 2: small runtime image ----
# Size note (~720 MB): python:3.12-slim is ~180 MB; the venv is ~400 MB and is almost all LiteLLM
# (212 MB incl. a 53 MB native extension) plus the dependencies it requires (botocore, openai,
# tokenizers, huggingface_hub). pytest/pygments are only ~16 MB, so splitting dev deps out would
# save ~4% for extra complexity. Slim base + multi-stage + no build caches is what is achievable
# while using LiteLLM, which the contract requires.
FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Non-root user. /data is created and owned by it, so the named volume
# mounted there inherits that ownership on first use.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser tests ./tests
COPY --chown=appuser:appuser pytest.ini ./

USER appuser
EXPOSE 8000

# Unhealthy if /health is not 200 (urlopen raises on 503, e.g. no keys loaded).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=4)"]

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
