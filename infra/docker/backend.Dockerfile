# Backend and worker image: FastAPI app, Temporal worker, Alembic migrations.
# Build from the repository root: docker build -f infra/docker/backend.Dockerfile -t actron-backend:dev .
#
# Layout inside the image matches the repository, so settings find the ontology without extra config:
#   /app/backend   the Python project and its virtual environment (working directory)
#   /app/ontology  the ontology files
#
# The docker CLI is here so the worker can start the Pi and test-runner containers through the mounted
# /var/run/docker.sock. The entrypoint drops to the unprivileged `actron` user unless that socket is
# mounted (the worker), because the socket and the host build directory are owned by the host user.
FROM docker:27-cli AS dockercli

FROM python:3.12.15-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    ACTRON_ONTOLOGY_DIR=/app/ontology \
    PATH=/app/backend/.venv/bin:$PATH

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates curl gosu \
 && rm -rf /var/lib/apt/lists/* \
 && pip install uv==0.12.3

COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker

RUN groupadd --gid 10001 actron \
 && useradd --uid 10001 --gid actron --create-home --shell /usr/sbin/nologin actron \
 && mkdir -p /app/backend /app/ontology /var/lib/actron/clones /var/lib/actron/builds \
 && chown -R actron:actron /app /var/lib/actron

WORKDIR /app/backend

# Dependencies first, so code changes do not reinstall them.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
COPY ontology/ /app/ontology/
RUN uv sync --frozen --no-dev \
 && chown -R actron:actron /app

# Written with printf so the file builds with and without BuildKit.
RUN printf '%s\n' \
    '#!/bin/sh' \
    'set -e' \
    'if [ "$(id -u)" = "0" ] && [ "${ACTRON_RUN_AS_ROOT:-}" != "1" ] && [ ! -S /var/run/docker.sock ]; then' \
    '  chown actron:actron /var/lib/actron 2>/dev/null || true' \
    '  exec gosu actron "$@"' \
    'fi' \
    'exec "$@"' > /usr/local/bin/actron-entrypoint \
 && chmod 0755 /usr/local/bin/actron-entrypoint

ARG ACTRON_VERSION=dev
ENV ACTRON_VERSION=${ACTRON_VERSION}

EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/actron-entrypoint"]
CMD ["uvicorn", "actron.api.app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
