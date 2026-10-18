# Pi coding agent image (spec B, B9; PRD 12). Pi has no sandbox, so this container is the boundary.
# Build: docker build -f infra/docker/pi.Dockerfile -t actron-pi:latest .
# The container receives one model key, the checkout at /work, the context at /context, and the
# MCP address. It never receives GitHub, Slack or Linear credentials.
FROM node:22.23.3-bookworm-slim AS node

FROM python:3.12.15-slim-bookworm

ARG PI_VERSION=1.3.0

# Node 22 (Pi needs >= 22.19) copied from the official image; git, ripgrep and a JDK 17 for ClojureScript builds.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git ripgrep openjdk-17-jdk-headless \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g --ignore-scripts "@earendil-works/pi-coding-agent@${PI_VERSION}" \
 && npm cache clean --force \
 && pip install --no-cache-dir pytest==8.4.2

# Entry wrapper: writes Pi's MCP (and optional custom provider) configuration from the environment into
# a tmpfs directory (PI_CODING_AGENT_DIR=/tmp/pi-agent), then runs pi with the given arguments. The run token
# is referenced as ${ACTRON_RUN_TOKEN} so Pi resolves it from the environment and it is never written to disk.
# (Written with printf because this Docker has no BuildKit, so Dockerfile heredocs are not available.)
RUN printf '%s\n' \
  '#!/usr/bin/env python3' \
  'import json, os, sys' \
  'home = os.environ.setdefault("PI_CODING_AGENT_DIR", "/tmp/pi-agent")' \
  'os.environ.setdefault("HOME", "/tmp")' \
  'os.environ["PI_SKIP_VERSION_CHECK"] = "1"' \
  'os.environ["PI_TELEMETRY"] = "0"' \
  'os.makedirs(home, exist_ok=True)' \
  'url = os.environ.get("ACTRON_MCP_URL", "")' \
  'if url:' \
  '    server = {"url": url, "headers": {"X-Actron-Run": "${ACTRON_RUN_TOKEN}"}, "exposure": "direct",' \
  '              "timeout": 30, "description": "Actron team-history graph: code, callers, tests, decisions"}' \
  '    with open(os.path.join(home, "mcp.json"), "w") as f:' \
  '        json.dump({"mcpServers": {"actron": server}}, f, indent=2)' \
  'base = os.environ.get("ACTRON_PI_BASE_URL", "")' \
  'if base:' \
  '    key_env = os.environ.get("ACTRON_PI_KEY_ENV", "OPENAI_API_KEY")' \
  '    provider = {"baseUrl": base, "api": os.environ.get("ACTRON_PI_API", "openai-completions"),' \
  '                "apiKey": "${" + key_env + "}", "models": [{"id": os.environ.get("ACTRON_PI_MODEL_ID", "default")}]}' \
  '    with open(os.path.join(home, "models.json"), "w") as f:' \
  '        json.dump({"providers": {"actron": provider}}, f, indent=2)' \
  'os.execvp("pi", ["pi", *sys.argv[1:]])' \
  > /usr/local/bin/actron-pi-entry \
 && chmod 0755 /usr/local/bin/actron-pi-entry \
 && useradd --create-home --uid 1000 --shell /bin/sh pi

USER 1000:1000
WORKDIR /work
ENTRYPOINT ["/usr/local/bin/actron-pi-entry"]
CMD ["--help"]
