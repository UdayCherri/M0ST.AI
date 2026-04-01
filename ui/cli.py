import difflib
import os
import platform
import shlex
import sys
import traceback

from core import load_env
from core.config import get_config

# All known CLI commands for autocomplete and suggestions
_ALL_COMMANDS = [
    "load", "list funcs", "info", "blocks", "insns", "edges",
    "explain", "pseudocode", "verify", "verification", "z3", "trace", "complexity",
    "export", "plugins", "snapshot", "status", "config",
    "ai ask", "ai pipeline",
    "find callers", "find callees", "find imports", "find strings", "find recursion",
    "show callgraph", "show dataflow",
    "similar", "clear", "entropy", "verbose",
    "help", "exit", "quit",
]


def _setup_readline():
    """Enable tab-completion via readline (or pyreadline3 on Windows)."""
    try:
        if platform.system() == "Windows":
            import pyreadline3  # noqa: F401
        import readline

        def _completer(text, state):
            text_lower = text.lower()
            line = readline.get_line_buffer().lstrip().lower()
            # If the line already has content, match multi-word commands
            matches = [c for c in _ALL_COMMANDS if c.startswith(line)]
            # Fall back to prefix matching
            if not matches:
                matches = [c for c in _ALL_COMMANDS if c.startswith(text_lower)]
            if state < len(matches):
                # Return only the part after what's already typed
                return matches[state] + " "
            return None

        readline.set_completer(_completer)
        readline.set_completer_delims("")
        readline.parse_and_bind("tab: complete")
    except (ImportError, Exception):
        pass  # Readline not available — tab completion disabled silently


def _suggest_command(cmd: str) -> str:
    """Return a 'did you mean?' suggestion for a mistyped command."""
    first_words = list({c.split()[0] for c in _ALL_COMMANDS})
    close = difflib.get_close_matches(cmd, first_words, n=1, cutoff=0.6)
    if close:
        return f"Unknown command: '{cmd}'. Did you mean '{close[0]}'? Type 'help' for usage."
    return f"Unknown command: '{cmd}'. Type 'help' for usage."


def _parse_addr(text: str) -> int:
    """Parse a hex or decimal address string."""
    text = text.strip()
    if text.startswith("0x") or text.startswith("-0x"):
        return int(text, 16)
    return int(text, 10)


def _safe_shlex_split(line: str):
    """shlex.split that doesn't crash on Windows unquoted backslashes."""
    try:
        return shlex.split(line, posix=(os.name != "nt"))
    except ValueError:
        return line.split()


def _print_banner():
    print()
    print("=" * 60)
    print("   M0ST - AI Security System.")
    print(f"   Platform: {platform.system()} {platform.machine()}")
    print("   Version:  2.0.0")
    print("=" * 60)
    print()


def _print_module_menu():
    print("  Select a module:\n")
    print("    [1] Reverse Engineering")
    print("    [2] Binary Analysis")
    print("    [3] Network Traffic Analysis")
    print()
    print("    [0] Full Mode (all modules)")
    print()


def _print_help(page: str = ""):
    pages = {
        "general": (
            "\n  General Commands:\n"
            "  load <binary>              Load and analyze a binary\n"
            "  list funcs                 List discovered functions\n"
            "  info <func_addr>           Show function properties\n"
            "  blocks <func_addr>         List basic blocks in a function\n"
            "  insns <bb_addr>            List instructions in a basic block\n"
            "  edges <func_addr>          Show CFG edges for a function\n"
            "  explain <func_addr>        Semantic summary (medium detail)\n"
            "  explain simple <addr>      Brief summary\n"
            "  explain deep <addr>        Detailed summary with vulns\n"
            "  pseudocode <func_addr>     Generate C-like pseudocode\n"
            "  verify                     Run symbolic verification (Z3)\n"
            "  z3                         Alias for symbolic verification\n"
            "  trace                      Re-run dynamic trace on loaded binary\n"
            "  complexity [func_addr]     Show cyclomatic complexity metrics\n"
            "  export <path>              Export analysis to JSON report\n"
            "  clear                      Clear graph and start fresh\n"
        ),
        "ai": (
            "\n  AI Commands:\n"
            "  ai name <addr>             LLM-based function naming\n"
            "  ai explain <addr>          LLM-based function summary\n"
            "  ai types <addr>            LLM-based type inference\n"
            "  ai refine <addr>           Integrated GNN + LLM analysis\n"
            "  ai full                    Full multi-agent AI analysis\n"
            "  ai vulns <addr>            LLM-based vulnerability detection\n"
            "  ai annotate <addr>         LLM-based code annotation\n"
            "  ai ask <question>          Free-form AI analyst query\n"
        ),
        "graph": (
            "\n  Graph Intelligence:\n"
            "  find callers <func_addr>   Find callers of a function\n"
            "  find callees <func_addr>   Find callees of a function\n"
            "  find imports <name>        Search imports by name\n"
            "  find strings <pattern>     Search strings by pattern\n"
            "  find recursion             Detect recursive functions\n"
            "  show callgraph             Display call graph summary\n"
            "  show dataflow <var>        Show data flow for a variable\n"
            "  similar <func_addr>        Find similar functions by embedding\n"
        ),
        "management": (
            "\n  Management:\n"
            "  plugins list               Show loaded plugins\n"
            "  plugins run <func_addr>    Run plugins on a function\n"
            "  snapshot save <name>       Save analysis snapshot\n"
            "  snapshot list              List snapshots\n"
            "  snapshot show <name>       Show snapshot details\n"
            "  snapshot diff <a> <b>      Diff two snapshots\n"
            "  status                     Show tool/service availability\n"
            "  config                     Show current configuration\n"
            "  verbose on|off             Toggle verbose output\n"
        ),
    }

    page = page.strip().lower()
    if page in pages:
        print(pages[page])
        return

    if page == "all":
        for section in pages.values():
            print(section)
        return

    # Show index
    print(
        "\n  Help Pages (type 'help <page>'):\n"
        "    help general      General analysis commands\n"
        "    help ai           AI-powered commands\n"
        "    help graph        Graph intelligence commands\n"
        "    help management   Plugins, snapshots, config\n"
        "    help all          Show all commands\n"
        "\n  help                       Show this index\n"
        "  quit / exit                Exit M0ST\n"
    )


def _check_tool_availability():
    """Check and report available tools (with timeouts to avoid hangs)."""
    import shutil

    checks = {}

    # radare2
    try:
        import r2pipe  # noqa: F401
        r2_path = get_config().get("tools", {}).get("r2_path") or ""
        checks["r2pipe"] = True
        # Check PATH first, then configured path, then common Windows install dirs
        r2_found = bool(shutil.which("radare2") or shutil.which("r2"))
        if not r2_found and r2_path:
            r2_found = bool(
                shutil.which(r2_path)
                or (os.path.isfile(r2_path))
                or (os.path.isfile(os.path.join(r2_path, "radare2.exe")))
                or (os.path.isfile(os.path.join(r2_path, "radare2")))
            )
        if not r2_found and os.name == "nt":
            _win_dirs = [
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "radare2", "bin"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "radare2", "bin"),
                r"C:\radare2\bin",
                r"C:\Program Files\radare2\bin",
                r"C:\Program Files (x86)\radare2\bin",
                os.path.join(os.environ.get("USERPROFILE", ""), "scoop", "apps", "radare2", "current", "bin"),
                os.path.join(os.environ.get("USERPROFILE", ""), "radare2", "bin"),
            ]
            r2_found = any(os.path.isfile(os.path.join(d, "radare2.exe")) for d in _win_dirs)
        checks["radare2"] = r2_found
    except ImportError:
        checks["r2pipe"] = False
        checks["radare2"] = False

    # GDB
    gdb_path = get_config().get("tools", {}).get("gdb_path") or "gdb"
    checks["gdb"] = bool(shutil.which(gdb_path))

    # pygdbmi
    try:
        import pygdbmi  # noqa: F401
        checks["pygdbmi"] = True
    except ImportError:
        checks["pygdbmi"] = False

    # z3
    try:
        import z3  # noqa: F401
        checks["z3-solver"] = True
    except ImportError:
        checks["z3-solver"] = False

    # OpenAI (also covers local/Ollama via compatible API)
    try:
        import openai  # noqa: F401
        checks["openai"] = True
    except ImportError:
        checks["openai"] = False

    # Anthropic
    try:
        import anthropic  # noqa: F401
        checks["anthropic"] = True
    except ImportError:
        checks["anthropic"] = False

    # PyTorch Geometric (GNN)
    try:
        import torch_geometric  # noqa: F401
        checks["torch-geometric"] = True
    except ImportError:
        checks["torch-geometric"] = False

    return checks


# ─────────────────────────────────────────────────────────────
# Command handlers - each returns True if the command was handled
# ─────────────────────────────────────────────────────────────


def _cmd_load(args, master, state):
    """Load and analyze a binary using the default pipeline."""
    if not args:
        print("Usage: load <binary_path>")
        return
    path = args[0]
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    if not os.path.isfile(path):
        print(f"File not found: {path}")
        return
    state["binary"] = path
    print(f"[M0ST] Loading binary: {path}")
    try:
        # Use the default pipeline: disassembly → CFG → call graph → PKG → snapshot
        master.planner.run_default_pipeline(path)
    except Exception as e:
        print(f"[M0ST] Pipeline error: {e}")


def _cmd_list_funcs(graph):
    """List all discovered functions."""
    try:
        funcs = graph.fetch_functions()
    except Exception as e:
        print(f"Error fetching functions: {e}")
        return
    if not funcs:
        print("No functions loaded. Use 'load <binary>' first.")
        return
    print(f"\n  {'Address':<20}{'Name'}")
    print("  " + "-" * 55)
    for f in funcs:
        addr = f.get("addr")
        name = f.get("name", "???")
        if addr is not None:
            print(f"  0x{addr:<18x}{name}")
        else:
            print(f"  {'???':<20}{name}")
    print(f"\n  Total: {len(funcs)} function(s)\n")


def _cmd_info(args, graph):
    """Show detailed info for a function."""
    if not args:
        print("Usage: info <func_addr>")
        return
    try:
        addr = _parse_addr(args[0])
    except Exception:
        print("Invalid address.")
        return
    try:
        funcs = graph.fetch_functions()
        func = next((f for f in funcs if f.get("addr") == addr), None)
    except Exception as e:
        print(f"Error: {e}")
        return
    if func is None:
        print(f"No function found at 0x{addr:x}.")
        return
    try:
        blocks = graph.fetch_basic_blocks(addr)
        edges = graph.fetch_flow_edges(addr)
    except Exception as e:
        print(f"Error: {e}")
        return
    print(f"\n  Function: {func.get('name', '???')}")
    print(f"  Address:  0x{addr:x}")
    print(f"  Blocks:   {len(blocks)}")
    print(f"  Edges:    {len(edges)}")
    for key, val in func.items():
        if key not in ("name", "addr"):
            print(f"    {key}: {val}")
    print()


def _cmd_blocks(args, graph):
    """List basic blocks in a function."""
    if not args:
        print("Usage: blocks <func_addr>")
        return
    try:
        addr = _parse_addr(args[0])
    except Exception:
        print("Invalid address.")
        return
    try:
        blocks = graph.fetch_basic_blocks(addr)
    except Exception as e:
        print(f"Error: {e}")
        return
    if not blocks:
        print(f"No blocks for function 0x{addr:x}.")
        return
    for bb in blocks:
        try:
            insns = graph.fetch_block_instructions(bb)
            print(f"  0x{bb:x}  ({len(insns)} instructions)")
        except Exception:
            print(f"  0x{bb:x}  (? instructions)")


def _cmd_insns(args, graph):
    """List instructions in a basic block."""
    if not args:
        print("Usage: insns <bb_addr>")
        return
    try:
        bb_addr = _parse_addr(args[0])
    except Exception:
        print("Invalid address.")
        return
    try:
        insns = graph.fetch_block_instructions(bb_addr)
    except Exception as e:
        print(f"Error: {e}")
        return
    if not insns:
        print(f"No instructions at block 0x{bb_addr:x}.")
        return
    for insn in insns:
        ops = insn.get("operands") or []
        ops_str = ", ".join(str(o) for o in ops) if ops else ""
        addr = insn.get("addr", 0)
        mnem = insn.get("mnemonic", "???")
        print(f"  0x{addr:x}  {mnem:<8} {ops_str}")


def _cmd_edges(args, graph):
    """Show CFG edges for a function."""
    if not args:
        print("Usage: edges <func_addr>")
        return
    try:
        addr = _parse_addr(args[0])
    except Exception:
        print("Invalid address.")
        return
    try:
        edges = graph.fetch_flow_edges(addr)
    except Exception as e:
        print(f"Error: {e}")
        return
    if not edges:
        print(f"No edges for function 0x{addr:x}.")
        return
    for s, d in edges:
        print(f"  0x{s:x} -> 0x{d:x}")


def _cmd_explain(args, semantic):
    """Generate semantic explanation of a function."""
    if not args:
        print("Usage: explain [simple|medium|deep] <func_addr>")
        return
    level = "medium"
    addr_str = args[0]
    if args[0] in {"simple", "deep", "medium"} and len(args) > 1:
        level = args[0]
        addr_str = args[1]
    try:
        addr = _parse_addr(addr_str)
    except Exception:
        print("Invalid function address.")
        return
    try:
        result = semantic.explain(addr, level=level)
    except Exception as e:
        print(f"Error generating explanation: {e}")
        return
    print(f"\n  {result.get('summary', 'No summary available.')}")
    for step in result.get("steps", []):
        print(f"    - {step}")
    if result.get("variables"):
        print(f"\n    Variables: {len(result['variables'])}")
    if result.get("vulnerabilities"):
        print("\n    Vulnerabilities:")
        for v in result["vulnerabilities"]:
            vtype = v.get("type", "unknown") if isinstance(v, dict) else str(v)
            detail = v.get("detail", "") if isinstance(v, dict) else ""
            print(f"      ! [{vtype}] {detail}")
    print()


def _cmd_pseudocode(args, cgen):
    """Generate C-like pseudocode for a function."""
    if not args:
        print("Usage: pseudocode <func_addr>")
        return
    try:
        addr = _parse_addr(args[0])
    except Exception:
        print("Invalid function address.")
        return
    try:
        code = cgen.decompile_function(addr)
        if isinstance(code, dict):
            pseudocode = code.get("normalized") or code.get("pseudocode", "// No pseudocode available")
            print()
            print(pseudocode)
        else:
            print()
            print(code)
    except Exception as e:
        print(f"Error generating pseudocode: {e}")


def _cmd_verify(master, graph, state):
    """Run symbolic analysis and verification on the current graph."""
    print("[M0ST] [Symbolic Analysis] Running verification pipeline...")
    binary = state.get("binary")

    # First pass: graph consistency verification.
    try:
        master.verifier_agent.verify_basicblock_edges()
    except Exception as e:
        print(f"[M0ST] Verifier error: {e}")
        return

    # Second pass: Z3-based symbolic pruning/verification.
    try:
        master.planner.run_symbolic_pipeline(binary)
    except Exception as e:
        print(f"[M0ST] Z3 analysis error: {e}")

    try:
        results = graph.get_verification_results()
    except Exception:
        results = None
    if results and isinstance(results, dict):
        print(f"  Static edges:    {results.get('static_edges', 0)}")
        print(f"  Runtime edges:   {results.get('runtime_edges', 0)}")
        print(f"  Suspect edges:   {results.get('suspect_edges', 0)}")
        bi = results.get("branch_issues", [])
        if bi:
            print(f"  Branch issues:   {len(bi)}")
        up = results.get("unsafe_patterns", [])
        if up:
            print(f"  Unsafe patterns: {len(up)}")
            for p in up:
                if isinstance(p, dict):
                    print(f"    ! [{p.get('type', '?')}] {p.get('detail', '')}")
                else:
                    print(f"    ! {p}")
    else:
        print("  No verification results.")
    print("  Symbolic stage: completed")
    print()


def _cmd_trace(master, state):
    """Run dynamic analysis on the loaded binary."""
    binary = state.get("binary")
    if not binary:
        print("No binary loaded. Use 'load <binary>' first.")
        return
    print(f"[M0ST] [Dynamic Analysis] Running runtime trace on {binary}...")
    try:
        master.planner.run_dynamic_pipeline(binary)
    except Exception as e:
        print(f"[M0ST] Trace error: {e}")


def _cmd_complexity(args, graph, cyclomatic_complexity, all_complexities):
    """Show cyclomatic complexity metrics."""
    if args:
        try:
            addr = _parse_addr(args[0])
        except Exception:
            print("Invalid function address.")
            return
        try:
            result = cyclomatic_complexity(graph, addr)
        except Exception as e:
            print(f"Error computing complexity: {e}")
            return
        print(f"\n  Cyclomatic Complexity for 0x{addr:x}:")
        print(f"    Nodes (basic blocks): {result['nodes']}")
        print(f"    Edges (flow edges):   {result['edges']}")
        print(f"    Complexity (M):       {result['complexity']}")
        print(f"    Classification:       {result['classification']}")
        print()
    else:
        try:
            results = all_complexities(graph)
        except Exception as e:
            print(f"Error computing complexities: {e}")
            return
        if not results:
            print("No functions loaded. Use 'load <binary>' first.")
            return
        # Get function names for display
        try:
            funcs = graph.fetch_functions()
            name_map = {f.get("addr"): f.get("name", "???") for f in funcs}
        except Exception:
            name_map = {}
        print(f"\n  {'Address':<20}{'Complexity':<12}{'Class':<16}{'Name'}")
        print("  " + "-" * 65)
        for r in results:
            addr = r["func_addr"]
            name = name_map.get(addr, "???")
            print(f"  0x{addr:<18x}{r['complexity']:<12}{r['classification']:<16}{name}")
        print()


def _cmd_export(args, graph, export_fn, state):
    """Export analysis to JSON."""
    if not args:
        print("Usage: export <output_path>")
        return
    try:
        abs_path = export_fn(
            graph,
            args[0],
            binary_path=state.get("binary"),
        )
        print(f"[M0ST] Analysis exported to: {abs_path}")
    except Exception as e:
        print(f"[M0ST] Export failed: {e}")


def _cmd_plugins(args, master, graph):
    """Manage and run plugins."""
    if not args:
        print("Usage: plugins list | plugins run <func_addr>")
        return
    if args[0] == "list":
        try:
            master.plugins.load_plugins()
            plist = master.plugins.list_plugins()
        except Exception as e:
            print(f"Error loading plugins: {e}")
            return
        if plist:
            print("\nLoaded plugins:")
            for p in plist:
                print(f"  - {p}")
        else:
            print("No plugins loaded.")
        print()
        return
    if args[0] == "run" and len(args) > 1:
        try:
            addr = _parse_addr(args[1])
        except Exception:
            print("Invalid function address.")
            return
        try:
            master.plugins.load_plugins()
            facts = master.plugins.run_all(graph, addr)
        except Exception as e:
            print(f"Plugin error: {e}")
            return
        if facts:
            print(f"\nPlugin findings for 0x{addr:x}:")
            for key, val in facts.items():
                if isinstance(val, list):
                    print(f"  {key}: {len(val)} finding(s)")
                    for item in val:
                        if isinstance(item, dict):
                            print(f"    - {item.get('detail', item)}")
                        else:
                            print(f"    - {item}")
                else:
                    print(f"  {key}: {val}")
        else:
            print("No plugin findings.")
        print()
        return
    print("Usage: plugins list | plugins run <func_addr>")


def _cmd_snapshot(args, snapshots):
    """Manage analysis snapshots."""
    if not args:
        print("Usage: snapshot save <name> | list | show <name> | diff <a> <b>")
        return

    if args[0] == "save" and len(args) >= 2:
        try:
            snapshots.create_snapshot(args[1], description="CLI snapshot")
            print(f"[M0ST] Snapshot saved: {args[1]}")
        except Exception as e:
            print(f"Error saving snapshot: {e}")
        return

    if args[0] == "list":
        try:
            snaps = snapshots.list_snapshots()
        except Exception as e:
            print(f"Error listing snapshots: {e}")
            return
        if snaps:
            print(f"\n  {'Name':<30}{'Created At'}")
            print("  " + "-" * 60)
            for s in snaps:
                name = s.get("name", "???") if isinstance(s, dict) else str(s)
                created = s.get("created_at", "???") if isinstance(s, dict) else "???"
                print(f"  {name:<30}{created}")
        else:
            print("No snapshots yet.")
        print()
        return

    if args[0] == "show" and len(args) >= 2:
        try:
            snap = snapshots.load_snapshot(args[1])
        except Exception as e:
            print(f"Error loading snapshot: {e}")
            return
        if snap and isinstance(snap, dict):
            print(f"\n  Snapshot: {snap.get('name', args[1])}")
            print(f"  Created:  {snap.get('created_at', '???')}")
            meta = snap.get("metadata", {})
            if isinstance(meta, dict):
                for k, v in meta.items():
                    if v is not None:
                        print(f"    {k}: {v}")
        else:
            print(f"Snapshot '{args[1]}' not found.")
        print()
        return

    if args[0] == "diff" and len(args) >= 3:
        try:
            diff = snapshots.diff_snapshots(args[1], args[2])
        except Exception as e:
            print(f"Error diffing snapshots: {e}")
            return
        if isinstance(diff, dict) and "error" in diff:
            print(f"Error: {diff['error']}. Missing: {diff.get('missing', [])}")
        elif isinstance(diff, dict):
            diffs = diff.get("diffs", {})
            if diffs:
                print(f"\n  Diffs between '{diff.get('a', '?')}' and '{diff.get('b', '?')}':")
                for key, val in diffs.items():
                    if isinstance(val, dict):
                        print(f"    {key}: {val.get('a')} -> {val.get('b')}")
                    else:
                        print(f"    {key}: {val}")
            else:
                print("Snapshots are identical.")
        print()
        return

    print("Usage: snapshot save <name> | list | show <name> | diff <a> <b>")


def _cmd_status():
    """Show tool/service availability."""
    avail = _check_tool_availability()
    print("\nTool/Service Status:")
    for tool, ok in sorted(avail.items()):
        status = "OK" if ok else "NOT FOUND"
        marker = "+" if ok else "-"
        print(f"  [{marker}] {tool}: {status}")
    print()


def _cmd_config():
    """Show current configuration."""
    config = get_config()
    print("\nCurrent Configuration:")
    for section, values in config.items():
        print(f"  [{section}]")
        if isinstance(values, dict):
            for k, v in values.items():
                display = "****" if "password" in k.lower() else v
                print(f"    {k}: {display}")
        else:
            print(f"    {values}")
    print()


# ─────────────────────────────────────────────────────────────
# AI command handler
# ─────────────────────────────────────────────────────────────


def _cmd_ai(args, master, state):
    """Handle AI-driven commands (LLM reasoning pipeline)."""
    import json as _json

    if not args:
        print(
            "Usage:\n"
            "  ai explain <addr>  LLM-based function summary (LLM reasoning)\n"
            "  ai name <addr>     LLM-based function naming\n"
            "  ai types <addr>    LLM-based type inference\n"
            "  ai refine <addr>   Integrated GNN + LLM analysis\n"
            "  ai vulns           Run vulnerability analysis on all functions\n"
            "  ai vulns <addr>    LLM-based vulnerability detection for function\n"
            "  ai annotate <addr> LLM-based code annotation\n"
            "  ai ask <question>  Free-form AI analyst query (LLM reasoning)\n"
            "  ai full            Full multi-agent AI analysis pipeline\n"
        )
        return

    subcmd = args[0].lower()

    # ai ask — free-form query (LLM reasoning pipeline)
    if subcmd == "ask":
        if len(args) < 2:
            print("Usage: ai ask <question>")
            return
        question = " ".join(args[1:])
        print(f"[M0ST] [LLM Reasoning] Processing query: {question}")
        try:
            result = master.semantic_agent.ask(question)
            answer = result.get("answer", "No answer available.")
            # Unwrap if LLM returned a JSON-formatted answer string
            if isinstance(answer, str):
                try:
                    parsed = _json.loads(answer)
                    if isinstance(parsed, dict):
                        answer = (parsed.get("answer") or parsed.get("text")
                                  or parsed.get("response") or parsed.get("result")
                                  or answer)
                except (ValueError, TypeError):
                    pass
            print(f"\n{answer}")
            ctx_funcs = result.get("context_functions", [])
            if ctx_funcs:
                print("\n  Referenced functions:")
                for cf in ctx_funcs:
                    if isinstance(cf, dict):
                        print(f"    {cf.get('addr', '?')}: {cf.get('name', '?')} ({cf.get('relation', '')})")
        except Exception as e:
            print(f"[M0ST] Error: {e}")
        print()
        return

    # ai full — full pipeline
    if subcmd == "full":
        binary = state.get("binary")
        if not binary:
            print("No binary loaded. Use 'load <binary>' first.")
            return
        print(f"[M0ST] Running full AI pipeline for {binary}...")
        try:
            result = master.planner.run_full_pipeline(binary)
            print(f"\n[M0ST] Analysis complete.")
            print(f"  Functions analyzed: {result.total_functions}")
            print(f"  Time: {result.total_time_seconds:.1f}s")
            print(f"  Stages completed: {', '.join(result.stages_completed)}")
            if result.naming_suggestions:
                print(f"  Naming suggestions: {len(result.naming_suggestions)}")
            if result.vulnerability_hints:
                print(f"  Vulnerability hints: {len(result.vulnerability_hints)}")
        except Exception as e:
            print(f"[M0ST] Pipeline error: {e}")
        return

    # ai vulns — full vulnerability analysis pipeline or per-function detection
    if subcmd == "vulns":
        if len(args) >= 2:
            # Per-function vulnerability detection
            try:
                addr = _parse_addr(args[1])
            except Exception:
                print("Invalid function address.")
                return
            
            print(f"[M0ST] Detecting vulnerabilities at 0x{addr:x}...")
            try:
                result = master.semantic_agent.detect_vulnerabilities(addr)
                vulns = result.get("vulnerabilities", [])
                if not vulns:
                    print(f"\n  No vulnerabilities detected for 0x{addr:x}.")
                else:
                    print(f"\n  Vulnerabilities for 0x{addr:x}:")
                    for v in vulns:
                        if isinstance(v, dict):
                            print(f"    ! [{v.get('severity', 'unknown')}] {v.get('type', '?')}")
                            print(f"      {v.get('description', '')}")
                        else:
                            print(f"    ! {v}")
            except Exception as e:
                print(f"[M0ST] Error: {e}")
        else:
            # Full binary vulnerability analysis pipeline
            print(f"[M0ST] [Vulnerability Analysis] Running full vulnerability detection pipeline...")
            try:
                result = master.planner.run_vulnerability_pipeline()
                print(f"\n[M0ST] Vulnerability analysis complete.")
                print(f"  Functions analyzed: {result.total_functions}")
                print(f"  Time: {result.total_time_seconds:.1f}s")
                if result.vulnerability_hints:
                    print(f"  Vulnerabilities found: {len(result.vulnerability_hints)}")
                    for addr, vulns in result.vulnerability_hints.items():
                        print(f"    0x{addr:x}: {len(vulns)} issue(s)")
            except Exception as e:
                print(f"[M0ST] Pipeline error: {e}")
        print()
        return

    # All other AI commands need an address
    if len(args) < 2:
        print(f"Usage: ai {subcmd} <func_addr>")
        return

    try:
        addr = _parse_addr(args[1])
    except Exception:
        print("Invalid function address.")
        return

    planner = master.planner

    try:
        if subcmd == "name":
            result = planner.ai_name(addr)
            if "error" in result:
                print(f"  Error: {result['error']}")
            else:
                print(f"\n  Suggested name: {result.get('name', '???')}")
                print(f"  Confidence:     {result.get('confidence', 0):.0%}")
                if result.get("reasoning"):
                    print(f"  Reasoning:      {result['reasoning']}")
            print()

        elif subcmd == "explain":
            print(f"[M0ST] [LLM Reasoning] Explaining function at 0x{addr:x}...")
            result = planner.ai_explain(addr)
            if "error" in result:
                print(f"  Error: {result['error']}")
            else:
                print(f"\n  Summary: {result.get('summary', 'No summary')}")
                if result.get("behavior"):
                    print(f"  Behavior: {result['behavior']}")
                if result.get("algorithmic_intent"):
                    print(f"  Intent: {result['algorithmic_intent']}")
                if result.get("side_effects"):
                    print(f"  Side effects:")
                    for se in result["side_effects"]:
                        print(f"    - {se}")
            print()

        elif subcmd == "types":
            result = planner.ai_types(addr)
            if "error" in result:
                print(f"  Error: {result['error']}")
            else:
                print(f"\n  Return type: {result.get('return_type', 'unknown')}")
                params = result.get("parameters", [])
                if params:
                    print("  Parameters:")
                    for p in params:
                        if isinstance(p, dict):
                            print(f"    {p.get('name', '?')}: {p.get('type', '?')}")
                        else:
                            print(f"    {p}")
                locals_ = result.get("locals", [])
                if locals_:
                    print("  Locals:")
                    for l in locals_:
                        if isinstance(l, dict):
                            print(f"    {l.get('name', '?')}: {l.get('type', '?')}")
                        else:
                            print(f"    {l}")
                if result.get("reasoning"):
                    print(f"  Reasoning: {result['reasoning']}")
            print()

        elif subcmd == "refine":
            result = planner.ai_refine(addr, state.get("binary"))
            if not result:
                print("  No results.")
            else:
                for key, val in result.items():
                    if isinstance(val, dict):
                        print(f"\n  [{key}]:")
                        for k, v in val.items():
                            if isinstance(v, (list, dict)):
                                text = _json.dumps(v, default=str)
                                if len(text) > 120:
                                    text = text[:120] + "..."
                                print(f"    {k}: {text}")
                            else:
                                print(f"    {k}: {v}")
                    else:
                        print(f"  {key}: {val}")
            print()

        elif subcmd == "vulns":
            result = master.semantic_agent.detect_vulnerabilities(addr)
            vulns = result.get("vulnerabilities", [])
            if not vulns:
                print(f"\n  No vulnerabilities detected for 0x{addr:x}.")
            else:
                print(f"\n  Vulnerabilities for 0x{addr:x}:")
                for v in vulns:
                    if isinstance(v, dict):
                        print(f"    ! [{v.get('severity', 'unknown')}] {v.get('type', '?')}")
                        print(f"      {v.get('description', '')}")
                    else:
                        print(f"    ! {v}")
            print()

        elif subcmd == "annotate":
            result = master.semantic_agent.annotate_function(addr)
            code = result.get("annotated_code", "// No annotation available")
            print(f"\n{code}\n")

        else:
            print(f"Unknown AI command: '{subcmd}'. Type 'ai' for usage.")

    except Exception as e:
        print(f"[M0ST] Error: {e}")


# ─────────────────────────────────────────────────────────────
# Graph intelligence commands
# ─────────────────────────────────────────────────────────────


def _cmd_find(args, graph):
    """Handle 'find callers/callees/imports/strings/recursion' commands."""
    if not args:
        print("Usage: find callers <addr> | find callees <addr> | find imports <name>\n"
              "       find strings <pattern> | find recursion")
        return

    subcmd = args[0].lower()

    if subcmd == "imports":
        if len(args) < 2:
            print("Usage: find imports <name_pattern>")
            return
        pattern = args[1]
        imports = graph.fetch_imports() if hasattr(graph, "fetch_imports") else []
        if not imports:
            print("  No imports loaded.")
            return
        matches = [i for i in imports
                   if isinstance(i, dict) and pattern.lower() in i.get("name", "").lower()]
        if not matches:
            print(f"  No imports matching '{pattern}'.")
            return
        print(f"\n  Imports matching '{pattern}':")
        for imp in matches:
            lib = imp.get("library", "")
            lib_str = f" ({lib})" if lib else ""
            print(f"    {imp.get('name', '?')}{lib_str}")
        print()
        return

    if subcmd == "strings":
        if len(args) < 2:
            print("Usage: find strings <pattern>")
            return
        pattern = args[1]
        if hasattr(graph, "search_strings"):
            matches = graph.search_strings(pattern)
        else:
            all_strings = graph.fetch_strings() if hasattr(graph, "fetch_strings") else []
            matches = [s for s in all_strings
                       if isinstance(s, dict) and pattern.lower() in s.get("value", "").lower()]
        if not matches:
            print(f"  No strings matching '{pattern}'.")
            return
        print(f"\n  Strings matching '{pattern}':")
        for s in matches[:50]:
            val = s.get("value", "?") if isinstance(s, dict) else str(s)
            addr = s.get("addr", "") if isinstance(s, dict) else ""
            addr_str = f" @ 0x{addr:x}" if isinstance(addr, int) else ""
            # Truncate long strings for display
            display_val = val[:80] + "..." if len(val) > 80 else val
            print(f"    {display_val}{addr_str}")
        if len(matches) > 50:
            print(f"    ... and {len(matches) - 50} more")
        print()
        return

    if subcmd == "recursion":
        call_edges = graph.fetch_call_edges() if hasattr(graph, "fetch_call_edges") else []
        funcs = graph.fetch_functions()
        name_map = {f.get("addr"): f.get("name", "???") for f in funcs}
        recursive = []
        for src, dst in call_edges:
            if src == dst:
                recursive.append(src)
        # Also find mutual recursion (A->B, B->A)
        edge_set = set(call_edges)
        mutual = []
        for src, dst in call_edges:
            if src != dst and (dst, src) in edge_set:
                pair = tuple(sorted([src, dst]))
                if pair not in mutual:
                    mutual.append(pair)
        if not recursive and not mutual:
            print("  No recursive functions detected.")
            return
        if recursive:
            print("\n  Direct recursion:")
            for addr in recursive:
                print(f"    0x{addr:x}  {name_map.get(addr, '???')}")
        if mutual:
            print("\n  Mutual recursion:")
            for a, b in mutual:
                print(f"    0x{a:x} ({name_map.get(a, '???')}) <-> 0x{b:x} ({name_map.get(b, '???')})")
        print()
        return

    if subcmd in ("callers", "callees"):
        if len(args) < 2:
            print(f"Usage: find {subcmd} <func_addr>")
            return
        try:
            addr = _parse_addr(args[1])
        except Exception:
            print("Invalid function address.")
            return

        if subcmd == "callers":
            results = graph.fetch_callers(addr) if hasattr(graph, "fetch_callers") else []
            label = "Callers"
        else:
            results = graph.fetch_callees(addr) if hasattr(graph, "fetch_callees") else []
            label = "Callees"

        if not results:
            print(f"  No {label.lower()} found for 0x{addr:x}.")
            return
        funcs = graph.fetch_functions()
        name_map = {f.get("addr"): f.get("name", "???") for f in funcs}
        print(f"\n  {label} of 0x{addr:x}:")
        for c in results:
            print(f"    0x{c:x}  {name_map.get(c, '???')}")
        print()
        return

    print("Usage: find callers <addr> | find callees <addr> | find imports <name>\n"
          "       find strings <pattern> | find recursion")


def _cmd_show(args, graph):
    """Handle 'show callgraph/dataflow' commands."""
    if not args:
        print("Usage: show callgraph | show dataflow <variable>")
        return

    subcmd = args[0].lower()

    if subcmd == "callgraph":
        edges = graph.fetch_call_edges() if hasattr(graph, "fetch_call_edges") else []
        funcs = graph.fetch_functions()
        name_map = {f.get("addr"): f.get("name", "???") for f in funcs}

        if not edges:
            print("  No call graph edges. Load a binary first.")
            return

        print(f"\n  Call Graph ({len(edges)} edges):")
        for src, dst in edges[:50]:
            src_name = name_map.get(src, f"0x{src:x}")
            dst_name = name_map.get(dst, f"0x{dst:x}")
            print(f"    {src_name} -> {dst_name}")
        if len(edges) > 50:
            print(f"    ... and {len(edges) - 50} more edges")
        print()

    elif subcmd == "dataflow":
        if len(args) < 2:
            print("Usage: show dataflow <variable_or_entity_id>")
            return
        entity_id = args[1]
        flows = graph.fetch_data_flows(entity_id) if hasattr(graph, "fetch_data_flows") else []
        if not flows:
            print(f"  No data flow edges for '{entity_id}'.")
            return
        print(f"\n  Data flows involving '{entity_id}':")
        for flow in flows[:30]:
            print(f"    {flow.get('src', '?')} --[{flow.get('type', '?')}]--> {flow.get('dst', '?')}")
        print()

    else:
        print("Usage: show callgraph | show dataflow <variable>")


def _cmd_similar(args, master):
    """Find functions similar to a given function via GNN embeddings."""
    if not args:
        print("Usage: similar <func_addr>")
        return
    try:
        addr = _parse_addr(args[0])
    except Exception:
        print("Invalid function address.")
        return

    print(f"[M0ST] [GNN Embeddings] Computing similar functions for 0x{addr:x}...")
    
    graph = master.graph_store
    funcs = graph.fetch_functions()
    name_map = {f.get("addr"): f.get("name", "???") for f in funcs}

    # Use the graph agent's embedding engine (GNN embeddings pipeline)
    try:
        similar = master.graph_agent.find_similar(addr)
        if not similar:
            print(f"  No similar functions found for 0x{addr:x}.")
            return
        print(f"\n  Functions similar to 0x{addr:x} ({name_map.get(addr, '???')}):")
        for s_addr, score in similar:
            print(f"    0x{s_addr:x}  {name_map.get(s_addr, '???')}  (similarity: {score:.3f})")
        print()
    except Exception as e:
        print(f"  Error computing similarity: {e}")


# ─────────────────────────────────────────────────────────────
# Main REPL
# ─────────────────────────────────────────────────────────────


def main():
    load_env()
    _print_banner()

    # ── Module selection ──────────────────────────────────────────
    _print_module_menu()
    module_choice = ""
    while module_choice not in {"0", "1", "2", "3"}:
        try:
            module_choice = input("  m0st [module]> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if module_choice not in {"0", "1", "2", "3"}:
            print("  Invalid choice. Enter 0, 1, 2, or 3.")

    _MODULE_NAMES = {"0": "Full Mode", "1": "Reverse Engineering", "2": "Binary Analysis", "3": "Network Traffic Analysis"}
    selected_module = _MODULE_NAMES[module_choice]
    print(f"\n[M0ST] Module: {selected_module}\n")

    # Check tool availability upfront
    print("[M0ST] Checking environment...")
    avail = _check_tool_availability()
    for tool, ok in sorted(avail.items()):
        status = "OK" if ok else "NOT FOUND"
        marker = "+" if ok else "-"
        print(f"  [{marker}] {tool}: {status}")
    print()

    # Lazy-import heavy modules
    from orchestration.master_agent import MasterAgent
    from analysis.complexity import cyclomatic_complexity, all_complexities
    from analysis.export import export_analysis_json

    master = MasterAgent()
    graph = master.graph_store
    semantic = master.semantic_agent
    cgen = master.pseudocode_agent
    snapshots = master.snapshots

    # Verbose defaults to off — user can toggle with 'verbose on/off'
    state = {"binary": None, "verbose": False, "module": selected_module}

    # Handle initial load from command-line args (skip flags)
    positional = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose_flag = "--verbose" in sys.argv or "-v" in sys.argv
    if verbose_flag:
        state["verbose"] = True
    if positional:
        initial_path = positional[0]
        abs_path = os.path.abspath(initial_path)
        if os.path.isfile(abs_path):
            state["binary"] = abs_path
            print(f"[M0ST] Running default pipeline for {abs_path}...")
            try:
                master.planner.run_default_pipeline(abs_path)
            except Exception as e:
                print(f"[M0ST] Pipeline error: {e}")
        else:
            print(f"[M0ST] Warning: file not found: {abs_path}")

    print("Type 'help' for commands.\n")

    _setup_readline()

    while True:
        try:
            line = input("m0st> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue
        if line in {"exit", "quit"}:
            break

        parts = _safe_shlex_split(line)
        if not parts:
            continue

        cmd = parts[0].lower()
        args = parts[1:]

        # ── help [page] ──────────────────────────────────
        if cmd == "help":
            _print_help(" ".join(args) if args else "")
            continue

        # ── verbose on/off ───────────────────────────────
        if cmd == "verbose":
            if args and args[0].lower() in ("on", "off"):
                state["verbose"] = args[0].lower() == "on"
                print(f"[M0ST] Verbose mode: {'ON' if state['verbose'] else 'OFF'}")
            else:
                print(f"  Verbose mode is {'ON' if state['verbose'] else 'OFF'}")
                print("  Usage: verbose on | verbose off")
            continue

        try:
            # ── load ─────────────────────────────────────
            if cmd == "load":
                _cmd_load(args, master, state)
                continue

            # ── list funcs ───────────────────────────────
            if cmd == "list" and args and args[0].lower() == "funcs":
                _cmd_list_funcs(graph)
                continue

            # ── info <addr> ──────────────────────────────
            if cmd == "info":
                _cmd_info(args, graph)
                continue

            # ── blocks <addr> ────────────────────────────
            if cmd == "blocks":
                _cmd_blocks(args, graph)
                continue

            # ── insns <bb_addr> ──────────────────────────
            if cmd == "insns":
                _cmd_insns(args, graph)
                continue

            # ── edges <addr> ─────────────────────────────
            if cmd == "edges":
                _cmd_edges(args, graph)
                continue

            # ── explain ──────────────────────────────────
            if cmd == "explain":
                _cmd_explain(args, semantic)
                continue

            # ── pseudocode ───────────────────────────────
            if cmd == "pseudocode":
                _cmd_pseudocode(args, cgen)
                continue

            # ── verify ───────────────────────────────────
            if cmd == "verify":
                _cmd_verify(master, graph, state)
                continue

            # ── z3 / verification aliases ───────────────
            if cmd in {"z3", "verification"}:
                _cmd_verify(master, graph, state)
                continue

            # ── trace ────────────────────────────────────
            if cmd == "trace":
                _cmd_trace(master, state)
                continue

            # ── complexity ───────────────────────────────
            if cmd == "complexity":
                _cmd_complexity(args, graph, cyclomatic_complexity, all_complexities)
                continue

            # ── export ───────────────────────────────────
            if cmd == "export":
                _cmd_export(args, graph, export_analysis_json, state)
                continue

            # ── plugins ──────────────────────────────────
            if cmd == "plugins":
                _cmd_plugins(args, master, graph)
                continue

            # ── snapshot ──────────────────────────────────
            if cmd == "snapshot":
                _cmd_snapshot(args, snapshots)
                continue

            # ── status ───────────────────────────────────
            if cmd == "status":
                _cmd_status()
                continue

            # ── config ───────────────────────────────────
            if cmd == "config":
                _cmd_config()
                continue

            # ── ai <subcmd> ──────────────────────────────
            if cmd == "ai":
                _cmd_ai(args, master, state)
                continue

            # ── find callers/callees ─────────────────────
            if cmd == "find" and args:
                _cmd_find(args, graph)
                continue

            # ── show callgraph/dataflow ──────────────────
            if cmd == "show" and args:
                _cmd_show(args, graph)
                continue

            # ── similar <func_addr> ─────────────────────
            if cmd == "similar":
                _cmd_similar(args, master)
                continue

            # ── clear ────────────────────────────────────
            if cmd == "clear":
                try:
                    graph.clear_graph()
                except Exception as e:
                    print(f"Error clearing graph: {e}")
                state["binary"] = None
                print("[M0ST] Graph cleared.")
                continue

            # ── entropy (alias) ──────────────────────────
            if cmd == "entropy" and args:
                _cmd_plugins(["run"] + args, master, graph)
                continue

            print(_suggest_command(cmd))

        except Exception as e:
            print(f"[M0ST] Command error: {e}")
            traceback.print_exc()


if __name__ == "__main__":
    main()
