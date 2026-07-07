# syntax=docker/dockerfile:1.7
# Single-image build used by chi-bench's local Docker backend.
#
# This image is self-contained: it carries both the chi-bench server
# runtime AND every prior-auth / care-management task's fixtures/worlds
# so a sandbox can run a trial by image pull alone. The agent and server
# share one sandbox at localhost; per-trial selection is driven by the
# CHI_BENCH_TASK_ID environment variable.
#
# Build context MUST be the repo root. Examples:
#   docker build -f docker/Dockerfile --target ci-skeleton -t chi-bench:ci .
#   docker build -f docker/Dockerfile -t chi-bench:latest .

FROM python:3.12-slim AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/workspace/.venv \
    PATH="/workspace/.venv/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git tini \
    && rm -rf /var/lib/apt/lists/*

# judge-harness:claude-code
# Install Node 20 + Claude Code CLI for the workspace-agent judge (verifier phase).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code@latest \
    && command -v claude \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Resolver shim so the WorkspaceJudge subprocess can always find `claude`.
# Harbor's stock claude-code agent install runs `curl claude.ai/install.sh | bash`,
# which deletes /usr/bin/claude (the npm-baked symlink) and installs into
# ~/.local/bin — a path NOT on the default container PATH for non-login
# `docker exec` shells. The verifier's `subprocess.run(["claude", ...])`
# (claude_runner.py) therefore raises FileNotFoundError post-install. This
# shim sits earlier on PATH than /usr/bin and routes to whichever real
# binary exists at exec time, surviving any installer rearrangement.
RUN printf '%s\n' \
    '#!/bin/sh' \
    'for p in "$HOME/.local/bin/claude" /root/.local/bin/claude /home/agent/.local/bin/claude /usr/bin/claude.real; do' \
    '  [ -x "$p" ] && exec "$p" "$@"' \
    'done' \
    'echo "claude binary not found in standard locations (~/.local/bin)" >&2' \
    'exit 127' \
    > /usr/local/bin/claude \
    && chmod +x /usr/local/bin/claude \
    && cp -L /usr/bin/claude /usr/bin/claude.real

WORKDIR /workspace

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock /workspace/
COPY src/ /workspace/src/

RUN uv sync --no-dev \
    && /workspace/.venv/bin/playwright install --with-deps chromium

# healthverse -> chi_bench compatibility shim (docker/shims/healthverse).
# The published chi-bench dataset's verifier entrypoints invoke
# `python -m healthverse.verifier.task_runtime` (and marathon's
# `...session_verifier`), expecting a `healthverse` package in the image. src/
# was renamed healthverse -> chi_bench, so install a `healthverse` alias package
# whose __path__ is chi_bench's. The build fails fast if the alias can't resolve.
COPY docker/shims/healthverse /workspace/.venv/lib/python3.12/site-packages/healthverse
RUN /workspace/.venv/bin/python -c "import importlib.util as u; assert u.find_spec('healthverse.verifier.task_runtime') and u.find_spec('healthverse.verifier.session_verifier'); print('healthverse alias OK')"

# CI build target: stops here, before any task data is copied. This stage
# is what CI uses to verify the Dockerfile parses and the dependency
# install succeeds without needing the data/ tree in the build context.
FROM base AS ci-skeleton

# Runtime build target (default): bakes the benchmark dataset, skills
# handbook, entrypoint, and runtime env into the image.
FROM base AS runtime

# Bake the benchmark dataset into the image. These are small JSONs
# (~O(MB) total) so the size cost is acceptable and it avoids any
# per-trial upload step.
# Cache-buster: bump on each cohort backfill so force_build=True
# actually invalidates the cached image.
ARG DATASET_CACHE_BUST=2026-06-30-healthverse-alias
COPY data/prior_auth_provider/shared/worlds /opt/chi-bench/worlds
COPY data/prior_auth_provider/tasks /opt/chi-bench/tasks
COPY data/prior_auth_um/tasks /opt/chi-bench/tasks
COPY data/care_management/shared/worlds /opt/chi-bench/worlds
COPY data/care_management/tasks /opt/chi-bench/tasks
COPY data/prior_auth_e2e/worlds /opt/chi-bench/worlds
COPY data/prior_auth_e2e/tasks /opt/chi-bench/tasks
COPY data/marathon /opt/chi-bench/tasks/marathon
COPY data/skills/managed-care-operations-handbook /workspace/skills/managed-care-operations-handbook
RUN mkdir -p /opt/chi-bench-task-assets
COPY data/care_management/shared/tool_reference.md /opt/chi-bench-task-assets/tool_reference.md

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Pre-create /logs/artifacts so entrypoint.sh routes chi-bench server logs
# there. Without this, the entrypoint falls back to /tmp and the server
# log is lost when the sandbox is reaped.
RUN mkdir -p /logs/artifacts

# Login-shell command runners (e.g. `bash -lc`) trigger Debian's
# /etc/profile, which clobbers the Dockerfile `ENV PATH=...` set above.
# Re-prepend the venv's bin dir for login shells so `python -m chi_bench.*`
# resolves to the venv, not system Python.
RUN echo 'export PATH="/workspace/.venv/bin:$PATH"' > /etc/profile.d/chi-bench.sh

ENV CHI_BENCH_RUNTIME_DIR=/tmp/chi-bench-runtime \
    CHI_BENCH_WORLDS_DIR=/opt/chi-bench/worlds \
    CHI_BENCH_PAYER_MODE=agent \
    CHI_BENCH_WORKSPACE_ROOT=/logs/artifacts/workspaces \
    CHI_BENCH_RAW_ROOT=/srv/chi-bench/raw \
    IS_SANDBOX=1

EXPOSE 8020 8023 8100 8200

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["sleep", "infinity"]
