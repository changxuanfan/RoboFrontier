# Frozen source is supplied by `robofrontier container build` using git archive.
FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm

ARG CODEX_VERSION=0.165.0
ARG CLAUDE_CODE_VERSION=2.1.316
ARG UV_VERSION=0.9.28
RUN apt-get update && apt-get install -y --no-install-recommends \
    libosmesa6 libegl1 libgl1 libglvnd0 libglib2.0-0 libseccomp2 ffmpeg git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install --global @openai/codex@${CODEX_VERSION} @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
    && npm cache clean --force \
    && pip install --no-cache-dir uv==${UV_VERSION}

WORKDIR /opt/RoboFrontier
COPY . .
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
RUN uv sync --locked --extra oracle \
    && .venv/bin/python -m scripts.install_antigravity --output /usr/local/bin/agy \
    && .venv/bin/python -m robofrontier.cli bootstrap \
    && rm -rf /root/.cache/uv /root/.cache/pip runs/asset-cache \
    && mkdir -p .robofrontier runs /var/tmp/robofrontier /opt/robofrontier-policy
ENV PATH="/opt/RoboFrontier/.venv/bin:${PATH}" \
    TMPDIR=/var/tmp/robofrontier ROBOFRONTIER_POLICY_ENV_BASE=/opt/robofrontier-policy \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
# The CLI sets CPU OSMesa or NVIDIA EGL explicitly from frozen task settings.
ENTRYPOINT ["python", "-m", "robofrontier.batch.container_entrypoint"]
