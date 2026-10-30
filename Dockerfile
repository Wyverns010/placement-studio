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
# Task 16 will use this to add the Laya gate weights (torch). Not installed yet.
# ARG WITH_LAYA=0
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY config ./config
COPY prompts ./prompts
COPY data ./data
COPY cache ./cache
COPY --from=web /build/web/dist ./web/dist
RUN useradd --create-home --uid 1000 app && chown -R app /srv
USER app
ENV PATH="/srv/.venv/bin:$PATH" PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-7860}"]
