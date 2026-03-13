import logging
import os
import platform
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

from core.capabilities import Capability
from core.config import get_config

try:
    from pygdbmi.gdbcontroller import GdbController
    _PYGDBMI_AVAILABLE = True
except ImportError:
    _PYGDBMI_AVAILABLE = False

logger = logging.getLogger("m0st.dynamic_agent")

# ---------------------------------------------------------------------------
# Strategy constants
# ---------------------------------------------------------------------------
STRATEGY_GDB = "gdb"
STRATEGY_DOCKER = "docker"
STRATEGY_WINDBG = "windbg"
STRATEGY_X64DBG = "x64dbg"


def _detect_strategy() -> str:
    """Choose the best dynamic analysis strategy for the current platform."""
    cfg = get_config()
    forced = cfg.get("dynamic", {}).get("strategy")
    if forced and forced in {STRATEGY_GDB, STRATEGY_DOCKER, STRATEGY_WINDBG, STRATEGY_X64DBG}:
        return forced

    if platform.system() != "Windows":
        return STRATEGY_GDB

    # On Windows: prefer WinDbg > x64dbg > Docker > skip
    windbg_path = cfg.get("tools", {}).get("windbg_path") or ""
    if windbg_path and shutil.which(windbg_path):
        return STRATEGY_WINDBG

    x64dbg_path = cfg.get("tools", {}).get("x64dbg_path") or ""
    if x64dbg_path and os.path.isfile(x64dbg_path):
        return STRATEGY_X64DBG

    if shutil.which("docker") and _docker_daemon_available():
        return STRATEGY_DOCKER

    return ""


def _docker_daemon_available() -> bool:
    """Return True only if the Docker daemon is reachable."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _detect_fallback_strategy() -> str:
    """Pick a non-docker dynamic strategy when docker is unavailable/fails."""
    cfg = get_config()

    if platform.system() == "Windows":
        windbg_path = cfg.get("tools", {}).get("windbg_path") or ""
        if windbg_path and shutil.which(windbg_path):
            return STRATEGY_WINDBG

        x64dbg_path = cfg.get("tools", {}).get("x64dbg_path") or ""
        if x64dbg_path and os.path.isfile(x64dbg_path):
            return STRATEGY_X64DBG

    gdb_path = cfg.get("tools", {}).get("gdb_path") or "gdb"
    if _PYGDBMI_AVAILABLE and shutil.which(gdb_path):
        return STRATEGY_GDB

    return ""


class DynamicAgent:
    """
    Executes the binary in a controlled environment.

    Supports multiple strategies:
    - **gdb** (Linux/macOS): pygdbmi-based step tracing via GDB/MI.
    - **docker**: Run a Linux GDB container on any platform.
    - **windbg**: Use the CDB command-line debugger on Windows.
    - **x64dbg**: Use x64dbg command-line on Windows.

    Strategy is auto-selected based on platform, or can be forced via
    ``config.yml`` → ``dynamic.strategy``.
    """
    CAPABILITIES = {Capability.DYNAMIC_EXECUTE}

    def __init__(self, graph_store, bus=None):
        self.g = graph_store
        self.bus = bus

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def run(self, binary_path: str, run_id: str = "run_1"):
        strategy = _detect_strategy()
        logger.info("Dynamic analysis strategy: %s", strategy or "none")

        if not os.path.isfile(binary_path):
            logger.warning("Binary not found: %s", binary_path)
            self._publish_ready(run_id, binary_path)
            return

        # Ask user permission for Docker (it launches containers)
        if strategy == STRATEGY_DOCKER:
            try:
                # Use stderr so prompt remains visible even in quiet mode.
                print(
                    "[DynamicAgent] Use Docker for dynamic analysis? [y/N] ",
                    file=sys.stderr,
                    end="",
                    flush=True,
                )
                answer = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = ""
            if answer not in ("y", "yes"):
                print("[DynamicAgent] Docker tracing skipped by user.", file=sys.stderr)
                self._publish_ready(run_id, binary_path)
                return
            if self._run_docker(binary_path, run_id, publish_ready=False):
                self._publish_ready(run_id, binary_path)
                return

            fallback = _detect_fallback_strategy()
            if fallback:
                print(
                    f"[DynamicAgent] Docker unavailable/failed. Falling back to '{fallback}'.",
                    file=sys.stderr,
                )
                if fallback == STRATEGY_GDB:
                    self._run_gdb(binary_path, run_id)
                elif fallback == STRATEGY_WINDBG:
                    self._run_windbg(binary_path, run_id)
                elif fallback == STRATEGY_X64DBG:
                    self._run_x64dbg(binary_path, run_id)
                else:
                    self._publish_ready(run_id, binary_path)
            else:
                print(
                    "[DynamicAgent] Docker unavailable/failed and no fallback backend found. Skipping dynamic trace.",
                    file=sys.stderr,
                )
                self._publish_ready(run_id, binary_path)
            return

        if strategy == STRATEGY_GDB:
            self._run_gdb(binary_path, run_id)
        elif strategy == STRATEGY_WINDBG:
            self._run_windbg(binary_path, run_id)
        elif strategy == STRATEGY_X64DBG:
            self._run_x64dbg(binary_path, run_id)
        else:
            logger.warning("No dynamic analysis backend available. Skipping.")
            self._publish_ready(run_id, binary_path)

    def _publish_ready(self, run_id: str, binary_path: str):
        if self.bus is not None:
            self.bus.publish("DYNAMIC_TRACE_READY",
                             {"run_id": run_id, "binary": binary_path})

    # ------------------------------------------------------------------
    # Strategy: Docker (platform-independent)
    # ------------------------------------------------------------------
    def _run_docker(self, binary_path: str, run_id: str, publish_ready: bool = True) -> bool:
        """Run GDB tracing inside a Docker container (Linux image)."""
        cfg = get_config()
        image = cfg.get("dynamic", {}).get("docker_image", "m0st/gdb-trace:latest")
        abs_path = os.path.abspath(binary_path)
        bin_dir = os.path.dirname(abs_path)
        bin_name = os.path.basename(abs_path)

        cmd = [
            "docker", "run", "--rm",
            "--security-opt", "seccomp=unconfined",
            "-v", f"{bin_dir}:/work:ro",
            image,
            "/work/" + bin_name,
        ]
        logger.info("Docker trace: %s", " ".join(cmd))
        ok = False
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                logger.error("Docker trace failed:\n%s", result.stderr[:500])
            else:
                self._parse_docker_output(result.stdout, run_id)
                ok = True
        except FileNotFoundError:
            logger.error("Docker not found on PATH.")
        except subprocess.TimeoutExpired:
            logger.error("Docker trace timed out.")
        if publish_ready:
            self._publish_ready(run_id, binary_path)
        return ok

    def _parse_docker_output(self, stdout: str, run_id: str):
        """Parse JSON lines from the docker trace container."""
        import json
        for line in stdout.strip().splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = rec.get("type")
            if kind == "bb_hit":
                self.g.add_executes_edge(
                    run_id=run_id,
                    bb_addr=rec.get("addr", 0),
                    seq=rec.get("seq", 0),
                    pc=rec.get("addr", 0),
                    next_pc=rec.get("next_pc", 0),
                    regs=rec.get("regs", {}),
                )

    # ------------------------------------------------------------------
    # Strategy: WinDbg / CDB (Windows)
    # ------------------------------------------------------------------
    def _run_windbg(self, binary_path: str, run_id: str):
        """Use CDB (command-line WinDbg) for lightweight trace."""
        cfg = get_config()
        cdb_path = cfg.get("tools", {}).get("windbg_path") or "cdb"

        bb_addrs = self.g.fetch_all_basic_blocks()
        if not bb_addrs:
            logger.warning("No basic blocks for WinDbg trace.")
            self._publish_ready(run_id, binary_path)
            return

        self.g.create_run(run_id, binary_path)

        # Build a CDB script that sets breakpoints and logs hits
        bp_cmds = []
        for addr in bb_addrs[:200]:  # limit breakpoints
            bp_cmds.append(f"bp 0x{addr:x}")
        bp_cmds.append("g")  # go
        script = "\n".join(bp_cmds) + "\nq\n"

        try:
            result = subprocess.run(
                [cdb_path, "-g", "-G", binary_path],
                input=script, capture_output=True, text=True, timeout=60
            )
            self._parse_cdb_output(result.stdout, run_id)
        except FileNotFoundError:
            logger.error("CDB not found at '%s'.", cdb_path)
        except subprocess.TimeoutExpired:
            logger.error("CDB trace timed out.")
        self._publish_ready(run_id, binary_path)

    def _parse_cdb_output(self, stdout: str, run_id: str):
        """Extract breakpoint hits from CDB output."""
        import re
        seq = 0
        for line in stdout.splitlines():
            m = re.search(r'Breakpoint\s+\d+\s+hit\s*.*?(0x[0-9a-fA-F]+)', line)
            if m:
                addr = int(m.group(1), 16)
                self.g.add_executes_edge(
                    run_id=run_id, bb_addr=addr, seq=seq,
                    pc=addr, next_pc=addr, regs={},
                )
                seq += 1

    # ------------------------------------------------------------------
    # Strategy: x64dbg (Windows)
    # ------------------------------------------------------------------
    def _run_x64dbg(self, binary_path: str, run_id: str):
        """Use x64dbg command-line interface for trace."""
        cfg = get_config()
        x64dbg_path = cfg.get("tools", {}).get("x64dbg_path", "")
        if not x64dbg_path or not os.path.isfile(x64dbg_path):
            logger.error("x64dbg not found at '%s'.", x64dbg_path)
            self._publish_ready(run_id, binary_path)
            return

        bb_addrs = self.g.fetch_all_basic_blocks()
        if not bb_addrs:
            logger.warning("No basic blocks for x64dbg trace.")
            self._publish_ready(run_id, binary_path)
            return

        self.g.create_run(run_id, binary_path)

        # x64dbg script: set breakpoints and run
        script_lines = []
        for addr in bb_addrs[:200]:
            script_lines.append(f"bp 0x{addr:x}")
        script_lines.append("run")
        script_lines.append("exit")
        script_content = "\n".join(script_lines)

        script_path = os.path.join(os.path.dirname(binary_path), "_m0st_trace.txt")
        try:
            with open(script_path, "w") as f:
                f.write(script_content)
            result = subprocess.run(
                [x64dbg_path, binary_path, "-s", script_path],
                capture_output=True, text=True, timeout=60,
            )
            logger.info("x64dbg exited with code %d", result.returncode)
        except FileNotFoundError:
            logger.error("x64dbg executable not found.")
        except subprocess.TimeoutExpired:
            logger.error("x64dbg trace timed out.")
        finally:
            if os.path.isfile(script_path):
                os.remove(script_path)
        self._publish_ready(run_id, binary_path)

    # ------------------------------------------------------------------
    # Strategy: GDB (Linux/macOS)
    # ------------------------------------------------------------------
    def _run_gdb(self, binary_path: str, run_id: str):
        if not _PYGDBMI_AVAILABLE:
            logger.warning("pygdbmi is not installed. Install it for dynamic tracing.")
            self._publish_ready(run_id, binary_path)
            return

        gdb_path = get_config().get("tools", {}).get("gdb_path") or "gdb"
        if not shutil.which(gdb_path):
            logger.warning("GDB not found at '%s'. Skipping dynamic trace.", gdb_path)
            self._publish_ready(run_id, binary_path)
            return

        bb_addrs = self.g.fetch_all_basic_blocks()
        if not bb_addrs:
            return

        self.g.create_run(run_id, binary_path)

        gdbmi = None
        try:
            gdbmi = GdbController(command=[gdb_path, "--interpreter=mi2", binary_path])
            self._send_cmd(gdbmi, "-gdb-set pagination off")
            self._send_cmd(gdbmi, "-gdb-set confirm off")

            for addr in bb_addrs:
                self._send_cmd(gdbmi, f"-break-insert *0x{addr:x}")

            self._send_cmd(gdbmi, "-exec-run")

            reg_names = self._get_register_names(gdbmi)
            seen_blocks = set()
            last_bb = None
            seq = 0
            pending_stop = None
            pending_from_step = False
            bb_set = set(bb_addrs)
            non_bb_hits = 0

            while True:
                stop = pending_stop or self._wait_for_stop(gdbmi)
                from_step = pending_from_step
                pending_stop = None
                pending_from_step = False
                if stop is None:
                    break
                reason = stop.get("reason")
                if self._is_exit_reason(reason):
                    break
                if reason not in {"breakpoint-hit", "end-stepping-range", "signal-received"}:
                    continue

                pc = self._parse_addr(stop)
                if pc is None:
                    pc = self._read_pc(gdbmi)
                if pc is None:
                    continue
                if pc not in bb_set:
                    non_bb_hits += 1
                    if non_bb_hits > 8:
                        self._send_cmd(gdbmi, "-exec-continue")
                    else:
                        self._send_cmd(gdbmi, "-exec-step-instruction")
                    continue
                non_bb_hits = 0

                regs = self._get_register_values(gdbmi, reg_names)
                self._record_syscall_if_any(run_id, seq, pc, regs, gdbmi)
                next_pc, pending_stop = self._step_for_next_pc(gdbmi)
                pending_from_step = pending_stop is not None

                self.g.add_executes_edge(
                    run_id=run_id, bb_addr=pc, seq=seq, pc=pc,
                    next_pc=next_pc if next_pc is not None else pc, regs=regs,
                )
                if last_bb is not None:
                    self.g.add_runtime_flow(
                        run_id=run_id, src_bb=last_bb, dst_bb=pc, seq=seq, pc=pc,
                        next_pc=next_pc if next_pc is not None else pc, regs=regs,
                    )

                seq += 1
                if pc in seen_blocks and not from_step:
                    break
                seen_blocks.add(pc)
                last_bb = pc

                if pending_stop is None:
                    self._send_cmd(gdbmi, "-exec-continue")

        finally:
            if gdbmi is not None:
                try:
                    gdbmi.exit()
                except Exception:
                    pass

        self._publish_ready(run_id, binary_path)

    def _send_cmd(self, gdbmi, cmd: str):
        gdbmi.write(cmd)

    def _wait_for_stop(self, gdbmi, timeout_sec: float = 1.0):
        while True:
            responses = gdbmi.get_gdb_response(timeout_sec=timeout_sec)
            if not responses:
                return None
            for resp in responses:
                if resp.get("type") == "notify" and resp.get("message") == "stopped":
                    payload = resp.get("payload", {})
                    if isinstance(payload, dict):
                        return payload

    def _parse_addr(self, stop_payload: Dict) -> Optional[int]:
        frame = stop_payload.get("frame")
        if not isinstance(frame, dict):
            return None
        addr = frame.get("addr")
        if isinstance(addr, str):
            try:
                return int(addr, 16)
            except Exception:
                return None
        if isinstance(addr, int):
            return addr
        return None

    def _read_pc(self, gdbmi) -> Optional[int]:
        gdbmi.write("-data-evaluate-expression $pc")
        responses = gdbmi.get_gdb_response(timeout_sec=1.0)
        for resp in responses:
            if resp.get("type") == "result" and resp.get("message") == "done":
                payload = resp.get("payload", {})
                value = payload.get("value")
                if isinstance(value, str):
                    try:
                        return int(value, 0)
                    except Exception:
                        return None
        return None

    def _get_register_names(self, gdbmi) -> List[str]:
        gdbmi.write("-data-list-register-names")
        responses = gdbmi.get_gdb_response(timeout_sec=1.0)
        for resp in responses:
            if resp.get("type") == "result" and resp.get("message") == "done":
                payload = resp.get("payload", {})
                names = payload.get("register-names")
                if isinstance(names, list):
                    return [n for n in names if isinstance(n, str)]
        return []

    def _get_register_values(self, gdbmi, reg_names: List[str]) -> Dict:
        gdbmi.write("-data-list-register-values x")
        responses = gdbmi.get_gdb_response(timeout_sec=1.0)
        for resp in responses:
            if resp.get("type") == "result" and resp.get("message") == "done":
                payload = resp.get("payload", {})
                values = payload.get("register-values")
                if not isinstance(values, list):
                    return {}
                regs = {}
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
                    if isinstance(idx, int) and idx < len(reg_names):
                        name = reg_names[idx]
                        regs[name] = val
                return regs
        return {}

    def _step_for_next_pc(self, gdbmi) -> Tuple[Optional[int], Optional[Dict]]:
        self._send_cmd(gdbmi, "-exec-step-instruction")
        stop = self._wait_for_stop(gdbmi)
        if stop is None:
            return None, None
        next_pc = self._parse_addr(stop)
        if next_pc is None:
            next_pc = self._read_pc(gdbmi)
        if stop.get("reason") == "breakpoint-hit":
            return next_pc, stop
        if stop.get("reason") == "signal-received":
            return next_pc, None
        return next_pc, None

    def _is_exit_reason(self, reason: Optional[str]) -> bool:
        if not reason:
            return False
        return reason.startswith("exited")

    def _record_syscall_if_any(self, run_id: str, seq: int, pc: int, regs: Dict, gdbmi):
        insn = self._read_current_instruction(gdbmi)
        if not insn:
            return
        text = insn.lower()
        if "syscall" in text:
            self._emit_syscall_event(run_id, seq, pc, regs)
            return
        if "int" in text and "0x80" in text:
            self._emit_syscall_event(run_id, seq, pc, regs)

    def _read_current_instruction(self, gdbmi) -> Optional[str]:
        gdbmi.write("-data-disassemble -s $pc -e $pc+1 -- 0")
        responses = gdbmi.get_gdb_response(timeout_sec=1.0)
        for resp in responses:
            if resp.get("type") == "result" and resp.get("message") == "done":
                payload = resp.get("payload", {})
                asm = payload.get("asm_insns")
                if isinstance(asm, list) and asm:
                    insn = asm[0]
                    if isinstance(insn, dict):
                        return insn.get("inst")
        return None

    def _emit_syscall_event(self, run_id: str, seq: int, pc: int, regs: Dict):
        syscall_num = self._read_reg(regs, ["rax", "eax"])
        args = [
            self._read_reg(regs, ["rdi", "edi"]),
            self._read_reg(regs, ["rsi", "esi"]),
            self._read_reg(regs, ["rdx", "edx"]),
            self._read_reg(regs, ["r10"]),
            self._read_reg(regs, ["r8"]),
            self._read_reg(regs, ["r9"]),
        ]
        if syscall_num is None:
            return
        self.g.add_syscall_event(run_id, seq, pc, syscall_num, args)

    def _read_reg(self, regs: Dict, names: List[str]) -> Optional[int]:
        for name in names:
            val = regs.get(name)
            if isinstance(val, str):
                try:
                    return int(val, 0)
                except Exception:
                    return None
            if isinstance(val, int):
                return val
        return None
