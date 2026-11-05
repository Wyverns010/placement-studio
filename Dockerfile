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
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 1000 app
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY prompts ./prompts
COPY data ./data
COPY --from=web /build/web/dist ./web/dist
# the venv stays root-owned (read-only for app); re-owning it would copy it into a new layer
RUN find /srv -path /srv/.venv -prune -o -exec chown app {} +
USER app
ENV PATH="/srv/.venv/bin:$PATH" PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-7860}"]
