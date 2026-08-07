# Operator frontend (feature 005). Multi-stage: node builds the SPA, python
# serves the API + the built static bundle. Build from the REPO ROOT so both
# `sr_agent/` (the kernel + pack, run from source like the tests) and
# `frontend/` are in context:
#
#   docker build -f frontend/Dockerfile -t sr-agent-frontend .
#
# ── Stage 1: build the Svelte SPA → frontend/ui/dist ─────────────────────────
FROM node:20-slim AS ui
WORKDIR /ui
COPY frontend/ui/package.json frontend/ui/package-lock.json* ./
RUN npm install
COPY frontend/ui/ ./
RUN npm run build

# ── Stage 2: python API server (runs the kernel from source) ─────────────────
FROM python:3.12-slim AS app
WORKDIR /app

# System deps: `git` is REQUIRED for the repo-URL target-ingestion mode (spec 021 —
# the backend shallow-clones a target repo). Without it, repo-URL sessions fail;
# path mode still works. `python:*-slim` has no git.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Runtime deps. Mirrors pyproject.toml [project.dependencies] + the backend's
# fastapi/uvicorn (frontend/backend/requirements.txt). We install deps only and
# run from source (PYTHONPATH=/app) — the project is not pip-packaged.
RUN pip install --no-cache-dir \
      "anthropic>=0.40.0" "web3>=7.0.0" "pydantic>=2.7.0" "click>=8.1.0" \
      "rich>=13.7.0" "docker>=7.0.0" "cryptography>=42.0.0" "langfuse>=2.0.0" \
      "requests>=2.31.0" "fastapi>=0.110" "uvicorn[standard]>=0.29"

# Kernel + pack + backend source, then the built SPA on top.
COPY sr_agent/ ./sr_agent/
COPY frontend/ ./frontend/
COPY --from=ui /ui/dist ./frontend/ui/dist

ENV PYTHONPATH=/app
EXPOSE 8000
# SR_SECRET_KEY (+ any endpoint/root overrides) come from the environment /
# docker-compose. The reasoning endpoint is set at runtime from the UI (US6).
CMD ["uvicorn", "frontend.backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
