"""
Master Agent — Backward-compatible orchestration layer.

Provides the MasterAgent class that initializes all agents and
delegates to the PlannerAgent for AI-driven analysis while
maintaining backward compatibility with the legacy CLI.
"""

import time
from datetime import datetime, timezone

from core import load_env
from core.config import get_config
from core.capabilities import Capability, enforce_capability
from storage.memory_graph_store import MemoryGraphStore
from storage.sqlite_store import SQLiteStore
from storage.snapshots import SnapshotManager
from plugins import PluginManager

# Import from new M0ST layer structure
from ai_security_agents.static_agent import StaticAgent
from ai_security_agents.heuristics_agent import HeuristicsAgent
from ai_security_agents.verifier_agent import VerifierAgent
from ai_security_agents.dynamic_agent import DynamicAgent
from ai_security_agents.semantic_agent import SemanticAgent
from ai_security_agents.graph_agent import GraphAgent
from ai_security_agents.llm_agent import LLMAgent
from ai_security_agents.pseudocode_agent import PseudocodeAgent
from ai_security_agents.llm_semantic_agent import LLMSemanticAgent
from ai_security_agents.z3_agent import Z3Agent
from orchestration.planner_agent import PlannerAgent


class MasterAgent:
    """
    Orchestration layer.

    Initializes all agents (static, dynamic, GNN, LLM, pseudocode,
    semantic, verifier, Z3) and provides both legacy pipeline
    compatibility and new AI-driven analysis via PlannerAgent.
    """

    def __init__(self):
        load_env()
        config = get_config()

        # ── Storage ────────────────────────────────────────────────────
        self.graph_store = MemoryGraphStore()
        self.sqlite_store = SQLiteStore(
            db_path=config.get("sqlite", {}).get("db_path", "storage/metadata.db")
        )
        self.snapshots = SnapshotManager(self.sqlite_store, graph_store=self.graph_store)
        self.plugins = PluginManager()

        # ── Legacy agents ──────────────────────────────────────────────
        self.static_agent = StaticAgent(self.graph_store)
        self.heuristics_agent = HeuristicsAgent(self.graph_store)
        self.verifier_agent = VerifierAgent(self.graph_store)
        self.dynamic_agent = DynamicAgent(self.graph_store)
        self.semantic_agent_legacy = SemanticAgent(self.graph_store)
        self.z3_agent = Z3Agent()

        # ── AI agents ──────────────────────────────────────────────────
        llm_provider = config.get("llm", {}).get("provider") or "none"
        llm_model = config.get("llm", {}).get("model") or None
        llm_api_key = config.get("llm", {}).get("api_key") or None
        llm_base_url = config.get("llm", {}).get("base_url") or None

        self.llm_agent = LLMAgent(
            provider=llm_provider,
            model=llm_model,
            api_key=llm_api_key,
            api_base=llm_base_url,
        )
        self.graph_agent = GraphAgent(self.graph_store)
        self.pseudocode_agent = PseudocodeAgent(self.graph_store)
        self.semantic_agent = LLMSemanticAgent(
            graph_store=self.graph_store,
            llm_agent=self.llm_agent,
            graph_agent=self.graph_agent,
            pseudocode_agent=self.pseudocode_agent,
        )

        # ── Planner ────────────────────────────────────────────────────
        self.planner = PlannerAgent(
            graph_store=self.graph_store,
            sqlite_store=self.sqlite_store,
            static_agent=self.static_agent,
            dynamic_agent=self.dynamic_agent,
            graph_agent=self.graph_agent,
            llm_agent=self.llm_agent,
            pseudocode_agent=self.pseudocode_agent,
            semantic_agent=self.semantic_agent,
            verifier_agent=self.verifier_agent,
            z3_agent=self.z3_agent,
            snapshot_manager=self.snapshots,
            plugin_manager=self.plugins,
        )

        # Register agents as LLM tools
        LLMAgent.register_tool(
            "static_analysis",
            lambda binary_path: self.static_agent.run(binary_path),
            "Run static analysis on a binary",
        )
        LLMAgent.register_tool(
            "graph_analysis",
            lambda func_addr: self.graph_agent.analyse_function(func_addr),
            "Run GNN structural analysis on a function",
        )
        LLMAgent.register_tool(
            "pseudocode",
            lambda func_addr, binary_path=None: self.pseudocode_agent.decompile_function(func_addr, binary_path),
            "Decompile a function to pseudocode",
        )

    # ── Legacy pipeline (backward compatible) ──────────────────────────

    def run_pipeline(self, binary_path: str, verbose: bool = False):
        """
        Run the analysis pipeline. Uses sequential execution
        instead of the old event bus.
        """
        import io as _io
        import logging as _logging
        import contextlib as _ctx

        def _log(msg: str):
            if verbose:
                print(msg)

        def _quiet_context():
            """Suppress stdout when not verbose (hides agent print calls)."""
            if verbose:
                return _ctx.nullcontext()
            return _ctx.redirect_stdout(_io.StringIO())

        # Silence Python loggers when not verbose (suppresses agent warnings)
        if not verbose:
            _logging.getLogger("m0st").setLevel(_logging.ERROR)
        else:
            _logging.getLogger("m0st").setLevel(_logging.DEBUG)

        _log("[Master] Clearing previous graph state...")
        self.graph_store.clear_graph()

        _log("[Master] Launching static analysis...")
        if enforce_capability(self.static_agent, Capability.STATIC_WRITE):
            with _quiet_context():
                self.static_agent.run(binary_path, verbose=verbose)

        _log("[Master] Running heuristics...")
        if enforce_capability(self.heuristics_agent, Capability.STATIC_READ):
            self.heuristics_agent.run()

        _log("[Master] Verifying static contradictions...")
        if enforce_capability(self.verifier_agent, Capability.VERIFY):
            self.verifier_agent.verify_basicblock_edges()

        _log("[Master] Running GNN analysis...")
        try:
            self.graph_agent.analyse_all_functions()
        except Exception as e:
            _log(f"[Master] GNN analysis skipped: {e}")

        _log("[Master] Starting dynamic tracing...")
        run_id = f"run_{int(time.time())}"
        if enforce_capability(self.dynamic_agent, Capability.DYNAMIC_EXECUTE):
            with _quiet_context():
                self.dynamic_agent.run(binary_path, run_id=run_id)

        _log("[Master] Verifying runtime edges...")
        if enforce_capability(self.verifier_agent, Capability.VERIFY):
            self.verifier_agent.verify_basicblock_edges()

        _log("[Master] Running plugins...")
        if enforce_capability(self.plugins, Capability.PLUGIN_ANALYSIS):
            self.plugins.load_plugins()
            for func in self.graph_store.fetch_functions():
                addr = func.get("addr")
                if addr is None:
                    continue
                self.plugins.run_all(self.graph_store, addr)

        _log("[Master] Generating semantic explanations...")
        semantic_results = {}
        funcs = self.graph_store.fetch_functions()
        total = len(funcs)

        if not verbose and total > 0:
            import threading as _threading

            _SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            _spinner_state = {"done": False, "current": 0, "frame": 0}

            def _spin():
                import time as _time
                while not _spinner_state["done"]:
                    frame = _SPINNER_FRAMES[_spinner_state["frame"] % len(_SPINNER_FRAMES)]
                    cur = _spinner_state["current"]
                    msg = f"\r[Master] Analyzing functions {frame} {cur}/{total} "
                    print(msg, end="", flush=True)
                    _spinner_state["frame"] += 1
                    _time.sleep(0.08)

            _spin_thread = _threading.Thread(target=_spin, daemon=True)
            _spin_thread.start()

        for i, func in enumerate(funcs, 1):
            addr = func.get("addr")
            if addr is None:
                continue
            name = func.get("name", f"sub_{addr:x}")
            if not verbose:
                _spinner_state["current"] = i
            else:
                print(f"  [{i}/{total}] Explaining {name} @ 0x{addr:x}...")
            try:
                semantic_results[addr] = self.semantic_agent.explain(addr)
            except Exception:
                try:
                    semantic_results[addr] = self.semantic_agent_legacy.explain_function(addr)
                except Exception:
                    pass

        if not verbose and total > 0:
            _spinner_state["done"] = True
            _spin_thread.join()
            print(f"\r[Master] Analyzing functions  done. ({total} function(s))   ")
        self.graph_store.set_semantic_summaries(semantic_results)

        _log("[Master] Creating snapshot...")
        snapshot_name = f"snapshot_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        if enforce_capability(self.snapshots, Capability.SNAPSHOT):
            try:
                self.snapshots.create_snapshot(snapshot_name, description="Pipeline snapshot")
            except Exception as e:
                _log(f"[Master] Snapshot creation skipped: {e}")

        # ── Security intelligence modules ──────────────────────────────
        _log("[Master] Running exploitability analysis...")
        try:
            from security_modules.ai_assisted_binary_analysis.vulnerability_detection import VulnerabilityDetector
            from security_modules.ai_assisted_binary_analysis.exploitability_analysis import ExploitabilityAnalyzer
            vd = VulnerabilityDetector()
            ea = ExploitabilityAnalyzer(self.graph_store)
            for func in self.graph_store.fetch_functions():
                addr = func.get("addr")
                if addr is not None:
                    vuln_result = vd.detect_vulnerabilities(self.graph_store, addr)
                    vulns = vuln_result.get("vulnerabilities", [])
                    if vulns:
                        ea.analyze(vulns)
        except Exception as e:
            print(f"[Master] Exploitability analysis skipped: {e}")

        _log("[Master] Running unsafe pattern detection...")
        try:
            from security_modules.ai_assisted_binary_analysis.unsafe_pattern_detection import UnsafePatternDetector
            upd = UnsafePatternDetector(self.graph_store)
            for func in self.graph_store.fetch_functions():
                addr = func.get("addr")
                if addr is not None:
                    upd.detect(self.graph_store, addr)
        except Exception as e:
            print(f"[Master] Unsafe pattern detection skipped: {e}")

        # Summary line always prints
        func_count = len(self.graph_store.fetch_functions())
        print(f"[Master] Pipeline complete. {func_count} function(s) analyzed.")

    # ── AI-driven pipeline ─────────────────────────────────────────────

    def run_ai_pipeline(self, binary_path: str):
        """Run the full AI-driven analysis pipeline via PlannerAgent."""
        return self.planner.run_full_pipeline(binary_path)
