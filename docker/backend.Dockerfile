# =============================================================================
# M0ST — AI Security System
# backend.Dockerfile
#
# Multi-stage build:
#   Stage 1 (r2-builder) — compiles radare2 from source into /opt/radare2
#   Stage 2 (runtime)    — lean Python image with r2 + GDB + M0ST source
# =============================================================================

# ── Stage 1: build radare2 ───────────────────────────────────────────────────
FROM python:3.11-slim AS r2-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    ninja-build \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# meson is required by radare2 5.x build system
RUN pip install --no-cache-dir meson

# Clone and install radare2 into a clean prefix so we can copy it
# with no build-tool leakage into the runtime stage.
ARG R2_BRANCH=master
RUN git clone --depth=1 --branch ${R2_BRANCH} \
    https://github.com/radareorg/radare2.git /tmp/r2 \
    && cd /tmp/r2 \
    && meson setup build \
    --prefix=/opt/radare2 \
    --buildtype=release \
    -Duse_sys_magic=false \
    && ninja -C build -j"$(nproc)" \
    && ninja -C build install \
    && rm -rf /tmp/r2

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim

LABEL org.opencontainers.image.title="M0ST AI Security System"
LABEL org.opencontainers.image.description="Modular AI-powered binary analysis platform"
LABEL org.opencontainers.image.source="https://github.com/CYB3R-BO1/M0ST"
LABEL org.opencontainers.image.licenses="See repo"

# Runtime system packages: GDB for dynamic tracing, libmagic for file typing
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdb \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Copy radare2 binaries + libraries from the builder stage
COPY --from=r2-builder /opt/radare2 /opt/radare2
ENV PATH="/opt/radare2/bin:${PATH}"
ENV LD_LIBRARY_PATH="/opt/radare2/lib:${LD_LIBRARY_PATH:-}"

# Create an unprivileged analyst user — never run analysis as root
RUN useradd -m -u 1000 -s /bin/bash analyst

WORKDIR /app

# Install Python dependencies as root (system-wide) before switching user
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source (respects .dockerignore — secrets and binaries excluded)
COPY . .

# Make entrypoint executable and hand ownership to analyst
RUN chmod +x /app/docker/entrypoint.sh \
    && chown -R analyst:analyst /app

USER analyst

# Storage and binary work directories — can be overridden by volume mounts
RUN mkdir -p /app/storage /app/data/binaries

# Future REST API port
EXPOSE 8000

# Liveness check: verify radare2 + r2pipe are functional
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import r2pipe; r2 = r2pipe.open('--'); r2.quit(); print('ok')" 2>/dev/null \
    || python -c "import r2pipe; print('r2pipe ok')" || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "main.py"]
