# M0ST Docker Guide

This folder contains Docker assets for running M0ST in two modes:

- Main app container (`m0st`) for CLI analysis
- Isolated GDB trace sandbox (`m0st/gdb-trace`) for `dynamic.strategy: docker`

## Files

- `backend.Dockerfile`: main runtime image with Python, dependencies, radare2, and gdb
- `gdb-trace.Dockerfile`: minimal sandbox used for Docker-based dynamic tracing
- `entrypoint.sh`: generates `config.yml` from environment when not mounted
- `trace_runner.py`: emits JSON trace events consumed by `DynamicAgent`
- `compose.yml`: builds and runs services

## Quick Start

Build and run the main container:

```bash
docker compose -f docker/compose.yml up -d --build
```

Open the CLI:

```bash
docker compose -f docker/compose.yml exec m0st python main.py
```

## Build GDB Trace Sandbox

The trace sandbox is profile-gated so it does not build unless requested:

```bash
docker compose -f docker/compose.yml --profile gdb-trace build gdb-trace
```

This builds image `m0st/gdb-trace:latest`, which `DynamicAgent` uses when `dynamic.strategy: docker`.

## Configure Dynamic Docker Strategy

Set in `config.yml`:

```yaml
dynamic:
  strategy: docker
  docker_image: m0st/gdb-trace:latest
```

Or with environment variables for auto-generated config in container:

```env
DYNAMIC_STRATEGY=docker
```

## Manual Trace Sandbox Test

You can test the trace image directly:

```bash
docker run --rm \
  --security-opt seccomp=unconfined \
  -v "${PWD}/tests/binaries:/work:ro" \
  m0st/gdb-trace:latest \
  /work/run
```

Expected output is JSON lines like:

```json
{
  "type": "bb_hit",
  "addr": 4425,
  "next_pc": 4430,
  "regs": { "rip": "0x1149" },
  "seq": 0
}
```

## Common Issues

- `docker: command not found`: install Docker Desktop / Engine and ensure CLI is on PATH.
- No trace events emitted: ensure target binary is executable and can run in Debian-based container.
- Permission errors in trace container: `--security-opt seccomp=unconfined` is required for ptrace/gdb.
- LLM keys not available in container: set them in `.env` and use `docker compose ... up` from repo root.

## Security Notes

- `config.yml` and `.env` are excluded from image build context by `.dockerignore`.
- The trace container runs as non-root user `tracer`.
- The main container runs as non-root user `analyst`.
