# =============================================================================
# M0ST — GDB trace sandbox
#
# Minimal isolated execution environment used by DynamicAgent when
# dynamic.strategy = "docker".
#
# DynamicAgent calls:
#   docker run --rm \
#     --security-opt seccomp=unconfined \
#     -v <binary_dir>:/work:ro \
#     m0st/gdb-trace:latest \
#     /work/<binary_name>
#
# The trace_runner.py script emits JSON lines to stdout:
#   {"type":"bb_hit","addr":<pc>,"next_pc":<next>,"regs":{...},"seq":<n>}
# =============================================================================

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gdb \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# pygdbmi gives us a clean Python ↔ GDB MI interface
RUN pip3 install --no-cache-dir --break-system-packages pygdbmi

# Non-root user for the sandbox
RUN useradd -m -u 1001 -s /bin/bash tracer

COPY docker/trace_runner.py /trace_runner.py
RUN chmod +x /trace_runner.py

USER tracer

ENTRYPOINT ["python3", "/trace_runner.py"]
