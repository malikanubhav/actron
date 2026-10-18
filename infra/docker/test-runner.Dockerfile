# Test runner image (spec B, B9 step 5). Runs dependency installs (with network, no credentials) and the
# tests (with --network none). Never receives a model key or any provider credential.
# Build: docker build -f infra/docker/test-runner.Dockerfile -t actron-test-runner:latest .
# Decision: no headless VS Code test host libraries. Calva's unit tests (mocha + ts-node) run in plain Node;
# its integration tests that need VS Code are out of scope for the build step.
FROM node:22.23.3-bookworm-slim AS node

FROM eclipse-temurin:21-jdk-jammy AS jdk

FROM python:3.12.15-slim-bookworm

ARG CLOJURE_VERSION=1.12.6.1673

# JDK 21: shadow-cljs 3.x (Calva's ClojureScript build) needs class file version 65; Debian's JDK 17 fails with
# UnsupportedClassVersionError.
COPY --from=jdk /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk PATH=/opt/java/openjdk/bin:$PATH

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git rlwrap \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL -o /tmp/linux-install.sh \
      "https://github.com/clojure/brew-install/releases/download/${CLOJURE_VERSION}/linux-install.sh" \
 && bash /tmp/linux-install.sh \
 && rm /tmp/linux-install.sh \
 && npm install -g pnpm@9.15.9 \
 && npm cache clean --force \
 && pip install --no-cache-dir pytest==8.4.2 uv==0.9.5 \
 && useradd --create-home --uid 1000 --shell /bin/sh runner

USER 1000:1000
ENV HOME=/home/runner npm_config_update_notifier=false
WORKDIR /work
CMD ["sh", "-c", "node --version && python --version && java -version && clojure --version"]
