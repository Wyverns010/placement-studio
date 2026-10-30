# syntax=docker/dockerfile:1
# Stage 1: build the React app. web/ imports ../data/*.json, so data/ sits beside it.
FROM node:22-slim AS web
WORKDIR /build
COPY data ./data
COPY web ./web
WORKDIR /build/web
RUN npm ci && npm run build

# Stage 2: Python runtime.
FROM python:3.12-slim
# WITH_LAYA=1 adds the optional Laya gate (GATE_IMPL=laya): CPU-only torch (the lock pins the
# PyTorch CPU index on Linux) and the typed-decisions checkpoint (~1.6 GB) baked into HF_HOME.
ARG WITH_LAYA=0
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 HF_HOME=/opt/hf
RUN useradd --create-home --uid 1000 app
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN if [ "$WITH_LAYA" = "1" ]; then uv sync --frozen --no-dev --group laya --no-install-project; \
    else uv sync --frozen --no-dev --no-install-project; fi
# Download in the same layer as the chown so the weights are not stored twice.
RUN if [ "$WITH_LAYA" = "1" ]; then \
      mkdir -p "$HF_HOME" && \
      .venv/bin/python -c "import laya; laya.load('convaiinnovations/laya', subfolder='typed-decisions', device='cpu')" && \
      chown -R app "$HF_HOME"; \
    fi
# From here on (including runtime) the Hub is never contacted: laya.load reads the baked cache.
# Harmless when WITH_LAYA=0 (nothing uses huggingface_hub then).
ENV HF_HUB_OFFLINE=1
COPY app ./app
COPY config ./config
COPY prompts ./prompts
COPY data ./data
COPY cache ./cache
COPY --from=web /build/web/dist ./web/dist
# the venv stays root-owned (read-only for app); re-owning it would copy it into a new layer
RUN find /srv -path /srv/.venv -prune -o -exec chown app {} +
USER app
ENV PATH="/srv/.venv/bin:$PATH" PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-7860}"]
