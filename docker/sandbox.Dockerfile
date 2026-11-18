# spec2ship sandbox: Python 3.12 with the target's locked deps and the gate tools.
# Built once per uv.lock. Runs use --network none, so nothing installs at run time.
# Base images are pinned by digest, so the content-hash tag in factory/sandbox.py
# names one exact image on every machine. Bump a digest on purpose, never by drift.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /build
COPY pyproject.toml uv.lock ./
# The factory package itself is not installed: only the target's deps and dev tools.
RUN uv sync --frozen --no-install-project --group target --group dev \
    && rm -rf /root/.cache

# Fallback non-root user; on Linux hosts the runner passes the host uid instead.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox

ENV PATH=/opt/venv/bin:$PATH \
    HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace
USER 10001:10001
