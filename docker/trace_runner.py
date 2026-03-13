#!/usr/bin/env python3
"""
Minimal GDB tracing runner for the Docker dynamic-analysis strategy.

Expected usage (from DynamicAgent):
  python3 /trace_runner.py /work/<binary>

Emits JSON lines on stdout in the format consumed by
DynamicAgent._parse_docker_output:
  {"type":"bb_hit","addr":...,"next_pc":...,"regs":{...},"seq":...}
"""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional, Tuple

from pygdbmi.gdbcontroller import GdbController  # type: ignore[reportMissingImports]


def _parse_addr(payload: Dict) -> Optional[int]:
    frame = payload.get("frame")
    if not isinstance(frame, dict):
        return None
    addr = frame.get("addr")
    if isinstance(addr, int):
        return addr
    if isinstance(addr, str):
        token = addr.split()[0]
        try:
            return int(token, 16 if token.startswith("0x") else 10)
        except Exception:
            return None
    return None


def _wait_for_stop(gdbmi: GdbController, timeout_sec: float = 1.0) -> Optional[Dict]:
    while True:
        responses = gdbmi.get_gdb_response(timeout_sec=timeout_sec)
        if not responses:
            return None
        for resp in responses:
            if resp.get("type") == "notify" and resp.get("message") == "stopped":
                payload = resp.get("payload", {})
                if isinstance(payload, dict):
                    return payload


def _send(gdbmi: GdbController, cmd: str) -> None:
    gdbmi.write(cmd)


def _read_pc(gdbmi: GdbController) -> Optional[int]:
    _send(gdbmi, "-data-evaluate-expression $pc")
    responses = gdbmi.get_gdb_response(timeout_sec=1.0)
    for resp in responses:
        if resp.get("type") == "result" and resp.get("message") == "done":
            payload = resp.get("payload", {})
            value = payload.get("value")
            if isinstance(value, str):
                token = value.split()[0]
                try:
                    return int(token, 0)
                except Exception:
                    return None
    return None


def _get_register_names(gdbmi: GdbController) -> List[str]:
    _send(gdbmi, "-data-list-register-names")
    responses = gdbmi.get_gdb_response(timeout_sec=1.0)
    for resp in responses:
        if resp.get("type") == "result" and resp.get("message") == "done":
            payload = resp.get("payload", {})
            names = payload.get("register-names")
            if isinstance(names, list):
                return [n for n in names if isinstance(n, str)]
    return []


def _get_register_values(gdbmi: GdbController, reg_names: List[str]) -> Dict[str, str]:
    _send(gdbmi, "-data-list-register-values x")
    responses = gdbmi.get_gdb_response(timeout_sec=1.0)
    for resp in responses:
        if resp.get("type") == "result" and resp.get("message") == "done":
            payload = resp.get("payload", {})
            values = payload.get("register-values")
            if not isinstance(values, list):
                return {}
            regs: Dict[str, str] = {}
            for item in values:
                if not isinstance(item, dict):
                    continue
                idx = item.get("number")
                val = item.get("value")
                if isinstance(idx, str):
                    try:
                        idx = int(idx, 10)
                    except Exception:
                        continue
                if isinstance(idx, int) and 0 <= idx < len(reg_names):
                    if isinstance(val, (str, int)):
                        regs[reg_names[idx]] = str(val)
            return regs
    return {}


def _emit(rec: Dict) -> None:
    print(json.dumps(rec, separators=(",", ":")), flush=True)


def _trace(binary_path: str, max_steps: int) -> int:
    gdbmi: Optional[GdbController] = None
    try:
        gdbmi = GdbController(command=["gdb", "--interpreter=mi2", binary_path])
        _send(gdbmi, "-gdb-set pagination off")
        _send(gdbmi, "-gdb-set confirm off")
        _send(gdbmi, "-gdb-set disassemble-next-line off")

        # Prefer a stable entry breakpoint if symbols exist; otherwise run directly.
        _send(gdbmi, "-break-insert main")
        _send(gdbmi, "-exec-run")

        reg_names = _get_register_names(gdbmi)
        seq = 0
        pending_stop: Optional[Dict] = None

        while seq < max_steps:
            stop = pending_stop or _wait_for_stop(gdbmi)
            pending_stop = None
            if stop is None:
                break

            reason = stop.get("reason")
            if isinstance(reason, str) and reason.startswith("exited"):
                break
            if reason not in {"breakpoint-hit", "end-stepping-range", "signal-received"}:
                _send(gdbmi, "-exec-continue")
                continue

            pc = _parse_addr(stop)
            if pc is None:
                pc = _read_pc(gdbmi)
            if pc is None:
                _send(gdbmi, "-exec-continue")
                continue

            regs = _get_register_values(gdbmi, reg_names)

            # Step once to estimate next PC. If we hit another stop right away,
            # keep it as pending so the next loop iteration processes it.
            _send(gdbmi, "-exec-step-instruction")
            next_stop = _wait_for_stop(gdbmi)
            next_pc = _parse_addr(next_stop) if isinstance(next_stop, dict) else None
            if next_pc is None:
                next_pc = _read_pc(gdbmi)
            if next_pc is None:
                next_pc = pc

            _emit(
                {
                    "type": "bb_hit",
                    "addr": pc,
                    "next_pc": next_pc,
                    "regs": regs,
                    "seq": seq,
                }
            )
            seq += 1

            if isinstance(next_stop, dict):
                next_reason = next_stop.get("reason")
                if isinstance(next_reason, str) and next_reason.startswith("exited"):
                    break
                pending_stop = next_stop
            else:
                _send(gdbmi, "-exec-continue")

        return 0
    except Exception as exc:
        print(f"[trace_runner] error: {exc}", file=sys.stderr)
        return 1
    finally:
        if gdbmi is not None:
            try:
                gdbmi.exit()
            except Exception:
                pass


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: trace_runner.py <binary_path>", file=sys.stderr)
        return 2

    binary_path = sys.argv[1]
    if not os.path.isfile(binary_path):
        print(f"[trace_runner] binary not found: {binary_path}", file=sys.stderr)
        return 2

    max_steps = int(os.environ.get("TRACE_MAX_STEPS", "800"))
    return _trace(binary_path, max_steps=max_steps)


if __name__ == "__main__":
    raise SystemExit(main())
