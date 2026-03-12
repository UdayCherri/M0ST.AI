"""
LLM Semantic Agent — AI-powered semantic analysis.

Replaces the legacy heuristics-based SemanticAgent with LLM + GNN
embedding-driven reasoning for function naming, variable naming,
type inference, behavior summarization, and code annotation.
"""

import json
import re
from typing import Any, Dict, List, Optional

from core.capabilities import Capability


class LLMSemanticAgent:
    """
    AI-powered semantic reasoning agent.

    Uses LLM + GNN embeddings to:
    - Infer function names
    - Suggest variable names
    - Infer types
    - Summarize function behavior
    - Infer algorithmic intent
    - Annotate code
    - Detect vulnerabilities

    Replaces old heuristic-based reasoning with LLM calls augmented
    by structural GNN embeddings.
    """

    CAPABILITIES = {Capability.SEMANTIC_REASON, Capability.STATIC_READ}

    def __init__(
        self,
        graph_store,
        llm_agent=None,
        graph_agent=None,
        pseudocode_agent=None,
    ):
        self.g = graph_store
        self.llm = llm_agent
        self.gnn = graph_agent
        self.pseudo = pseudocode_agent

    # ── Public API ─────────────────────────────────────────────────────────

    def explain(self, func_addr: int, level: str = "medium") -> Dict[str, Any]:
        """
        Generate semantic explanation at the requested detail level.
        Falls back to classical heuristics if LLM is unavailable.
        """
        if self.llm is not None and self.llm.client is not None:
            return self._explain_with_llm(func_addr, level)
        return self._explain_classical(func_addr, level)

    def infer_function_name(self, func_addr: int) -> Dict[str, Any]:
        context = self._gather_context(func_addr)
        if self.llm is None or self.llm.client is None:
            return {"name": self._classical_name(func_addr), "confidence": 0.3, "reasoning": "Classical heuristic"}
        return self.llm.infer_function_name(**context)

    def infer_variable_names(self, func_addr: int) -> Dict[str, Any]:
        context = self._gather_context(func_addr)
        if self.llm is None or self.llm.client is None:
            return {"variables": self._classical_variables(func_addr)}
        return self.llm.infer_variable_names(**context)

    def infer_types(self, func_addr: int) -> Dict[str, Any]:
        context = self._gather_context(func_addr)
        if self.llm is None or self.llm.client is None:
            return {"parameters": [], "return_type": "unknown", "locals": [], "reasoning": "No LLM available"}
        return self.llm.infer_types(**context)

    def summarize_function(self, func_addr: int) -> Dict[str, Any]:
        context = self._gather_context(func_addr)
        if self.llm is None or self.llm.client is None:
            return self._classical_summary(func_addr)
        result = self.llm.summarize_function(**context)
        # Retry once if LLM cold-start returned empty/error on first call
        if not result.get("summary"):
            result = self.llm.summarize_function(**context)
        if not result.get("summary"):
            return self._classical_summary(func_addr)
        return result

    def annotate_function(self, func_addr: int) -> Dict[str, Any]:
        context = self._gather_context(func_addr)
        if self.llm is None or self.llm.client is None:
            return {"annotated_code": context.get("pseudocode", "// No pseudocode available")}
        return self.llm.annotate_code(
            pseudocode=context.get("pseudocode", ""),
            disassembly=context.get("disassembly", ""),
            metadata=context.get("metadata"),
        )

    def detect_vulnerabilities(self, func_addr: int) -> Dict[str, Any]:
        context = self._gather_context(func_addr)
        if self.llm is None or self.llm.client is None:
            return {"vulnerabilities": self._classical_vulns(func_addr)}
        return self.llm.detect_vulnerabilities(
            disassembly=context.get("disassembly", ""),
            pseudocode=context.get("pseudocode", ""),
            metadata=context.get("metadata"),
        )

    def full_analysis(self, func_addr: int) -> Dict[str, Any]:
        return {
            "func_addr": func_addr,
            "name_inference": self.infer_function_name(func_addr),
            "variable_inference": self.infer_variable_names(func_addr),
            "type_inference": self.infer_types(func_addr),
            "summary": self.summarize_function(func_addr),
            "vulnerabilities": self.detect_vulnerabilities(func_addr),
        }

    def ask(self, question: str) -> Dict[str, Any]:
        """
        Handle free-form AI analyst queries.

        Gathers context from the PKG, builds a structured prompt,
        and invokes the LLM. The response always references PKG data.
        """
        # Parse question for address references
        addr_match = re.search(r"0x[0-9a-fA-F]+", question)
        target_addr = None
        if addr_match:
            try:
                target_addr = int(addr_match.group(), 16)
            except ValueError:
                pass

        # Build PKG context
        pkg_context = self._build_ask_context(question, target_addr)

        if self.llm is None or self.llm.client is None:
            return self._ask_classical(question, pkg_context)

        prompt = self.llm.build_prompt(
            task="analyst_query",
            instruction=(
                "You are an AI binary analysis assistant. Answer the user's question "
                "using ONLY the program data provided below. Reference specific "
                "addresses, functions, and structural data in your answer. "
                "Do not fabricate information not present in the data.\n\n"
                f"USER QUESTION: {question}"
            ),
            disassembly=pkg_context.get("disassembly", ""),
            pseudocode=pkg_context.get("pseudocode", ""),
            metadata=pkg_context.get("metadata"),
            gnn_embedding=pkg_context.get("gnn_embedding"),
        )

        try:
            response = self.llm.query(prompt)
            return {
                "question": question,
                "answer": response,
                "context_functions": pkg_context.get("metadata", {}).get("context_functions", []),
                "source": "llm",
            }
        except Exception as e:
            return {"question": question, "answer": f"Error: {e}", "source": "error"}

    def _build_ask_context(self, question: str, target_addr: Optional[int] = None) -> Dict[str, Any]:
        """Build context for a free-form query from the PKG."""
        context: Dict[str, Any] = {
            "disassembly": "",
            "pseudocode": "",
            "metadata": {},
        }

        question_lower = question.lower()

        # If asking about a specific function
        if target_addr is not None:
            # Works with both PKG (get_function) and MemoryGraphStore (fetch_functions)
            func = None
            if hasattr(self.g, "get_function"):
                func = self.g.get_function(target_addr)
            else:
                known = {f.get("addr") for f in self.g.fetch_functions()}
                if target_addr in known:
                    func = {"addr": target_addr}
            if func:
                return self._gather_context(target_addr)

        # If asking about crypto routines
        if "crypto" in question_lower:
            context["metadata"]["query_type"] = "crypto_search"
            crypto_funcs = []
            for func in self.g.fetch_functions():
                addr = func.get("addr")
                if addr is None:
                    continue
                annotations = self.g.get_annotations(hex(addr)) if hasattr(self.g, "get_annotations") else {}
                name = func.get("name", "")
                if any(k in name.lower() for k in ("crypt", "aes", "sha", "md5", "hash", "cipher")):
                    crypto_funcs.append(func)
                elif annotations:
                    crypto_funcs.append(func)
            context["metadata"]["crypto_candidates"] = [
                {"addr": f"0x{f['addr']:x}", "name": f.get("name", "?")} for f in crypto_funcs[:10]
            ]

        # If asking to trace input/data flow
        if "trace" in question_lower or "input" in question_lower or "flow" in question_lower:
            context["metadata"]["query_type"] = "dataflow_trace"
            data_flows = self.g.fetch_data_flows() if hasattr(self.g, "fetch_data_flows") else []
            context["metadata"]["data_flows"] = data_flows[:20]

        # General: provide function listing and call graph summary
        funcs = self.g.fetch_functions()
        context["metadata"]["total_functions"] = len(funcs)
        context["metadata"]["function_list"] = [
            {"addr": f"0x{f['addr']:x}", "name": f.get("name", "?")}
            for f in funcs[:30]
        ]

        call_edges = self.g.fetch_call_edges() if hasattr(self.g, "fetch_call_edges") else []
        context["metadata"]["call_graph_edges"] = len(call_edges)

        # PKG summary
        if hasattr(self.g, "summary"):
            context["metadata"]["pkg_summary"] = self.g.summary()

        return context

    def _ask_classical(self, question: str, pkg_context: Dict) -> Dict[str, Any]:
        """Classical (non-LLM) response to free-form queries."""
        metadata = pkg_context.get("metadata", {})
        parts = [f"PKG contains {metadata.get('total_functions', 0)} functions."]

        func_list = metadata.get("function_list", [])
        if func_list:
            parts.append("Functions:")
            for f in func_list[:10]:
                parts.append(f"  {f['addr']}: {f['name']}")

        return {
            "question": question,
            "answer": "\n".join(parts),
            "source": "classical",
        }

    # ── Context gathering ──────────────────────────────────────────────────

    def _gather_context(self, func_addr: int) -> Dict[str, Any]:
        context = {
            "disassembly": "",
            "pseudocode": "",
            "metadata": {},
            "gnn_embedding": None,
        }

        blocks = self.g.fetch_basic_blocks(func_addr)
        edges = self.g.fetch_flow_edges(func_addr)

        disasm_lines = []
        for bb in blocks:
            insns = self.g.fetch_block_instructions(bb)
            disasm_lines.append(f"; Block 0x{bb:x}")
            for insn in insns:
                addr = insn.get("addr", 0)
                mnem = insn.get("mnemonic", "???")
                ops = ", ".join(str(o) for o in insn.get("operands", []))
                disasm_lines.append(f"  0x{addr:x}: {mnem} {ops}")

        context["disassembly"] = "\n".join(disasm_lines)

        func_name = self._lookup_function_name(func_addr)
        calls = self._collect_calls(blocks)

        # Build call chains for context enhancement
        call_chains = self._build_call_chains(func_addr)
        context_functions = self._select_context_functions(func_addr)
        dataflow_summary = self._build_dataflow_summary(blocks)

        context["metadata"] = {
            "func_name": func_name,
            "func_addr": f"0x{func_addr:x}",
            "block_count": len(blocks),
            "edge_count": len(edges),
            "calls": calls,
            "call_chains": call_chains,
            "context_functions": context_functions,
            "dataflow_summary": dataflow_summary,
        }

        if self.pseudo is not None:
            try:
                pseudo_result = self.pseudo.decompile_function(func_addr)
                if pseudo_result and pseudo_result.get("normalized"):
                    context["pseudocode"] = pseudo_result["normalized"]
                elif pseudo_result and pseudo_result.get("pseudocode"):
                    context["pseudocode"] = pseudo_result["pseudocode"]
            except Exception:
                pass

        if self.gnn is not None:
            try:
                gnn_result = self.gnn.analyse_function(func_addr)
                context["gnn_embedding"] = gnn_result.get("graph_embedding")
            except Exception:
                pass

        return context

    def _build_call_chains(self, func_addr: int, depth: int = 3) -> List[str]:
        """Extract call chains for context enhancement."""
        chains = []
        callees = self.g.fetch_callees(func_addr) if hasattr(self.g, "fetch_callees") else []
        callers = self.g.fetch_callers(func_addr) if hasattr(self.g, "fetch_callers") else []

        for caller in callers[:3]:
            caller_name = self._lookup_function_name(caller)
            func_name = self._lookup_function_name(func_addr)
            chains.append(f"{caller_name} -> {func_name}")

        for callee in callees[:5]:
            func_name = self._lookup_function_name(func_addr)
            callee_name = self._lookup_function_name(callee)
            chains.append(f"{func_name} -> {callee_name}")

        return chains

    def _select_context_functions(self, func_addr: int, max_ctx: int = 3) -> List[Dict[str, Any]]:
        """Select related functions to provide context for LLM reasoning."""
        context_funcs = []

        # Include callers
        callers = self.g.fetch_callers(func_addr) if hasattr(self.g, "fetch_callers") else []
        for caller in callers[:max_ctx]:
            name = self._lookup_function_name(caller)
            blocks = self.g.fetch_basic_blocks(caller)
            context_funcs.append({
                "addr": f"0x{caller:x}",
                "name": name,
                "relation": "caller",
                "block_count": len(blocks),
            })

        # Include callees
        callees = self.g.fetch_callees(func_addr) if hasattr(self.g, "fetch_callees") else []
        for callee in callees[:max_ctx]:
            name = self._lookup_function_name(callee)
            blocks = self.g.fetch_basic_blocks(callee)
            context_funcs.append({
                "addr": f"0x{callee:x}",
                "name": name,
                "relation": "callee",
                "block_count": len(blocks),
            })

        return context_funcs

    def _build_dataflow_summary(self, blocks: List[int]) -> str:
        reads = set()
        writes = set()
        calls = []

        for bb in blocks:
            insns = self.g.fetch_block_instructions(bb)
            for insn in insns:
                mnem = (insn.get("mnemonic") or "").lower()
                ops = insn.get("operands", [])

                if mnem in ("mov", "lea", "movzx", "movsx") and len(ops) >= 2:
                    writes.add(ops[0])
                    reads.add(ops[1])
                elif mnem in ("push",) and ops:
                    reads.add(ops[0])
                elif mnem in ("pop",) and ops:
                    writes.add(ops[0])
                elif mnem in ("call", "bl", "blr") and ops:
                    calls.append(ops[0])

        parts = []
        if writes:
            parts.append(f"Writes: {', '.join(sorted(writes)[:10])}")
        if reads:
            parts.append(f"Reads: {', '.join(sorted(reads)[:10])}")
        if calls:
            parts.append(f"Calls: {', '.join(calls[:10])}")

        return "; ".join(parts)

    # ── Classical (non-LLM) fallback methods ───────────────────────────────

    def _explain_with_llm(self, func_addr: int, level: str) -> Dict[str, Any]:
        context = self._gather_context(func_addr)

        if level == "simple":
            result = self.llm.summarize_function(**context)
            return {
                "summary": result.get("summary", "No summary available."),
                "steps": [result.get("behavior", "")],
                "variables": [],
                "vulnerabilities": [],
            }
        elif level == "deep":
            summary = self.llm.summarize_function(**context)
            vulns = self.llm.detect_vulnerabilities(
                disassembly=context.get("disassembly", ""),
                pseudocode=context.get("pseudocode", ""),
                metadata=context.get("metadata"),
            )
            types = self.llm.infer_types(**context)

            vuln_list = vulns.get("vulnerabilities", [])
            return {
                "summary": summary.get("summary", "No summary available."),
                "steps": [
                    summary.get("behavior", ""),
                    summary.get("algorithmic_intent", ""),
                    f"Complexity: {summary.get('complexity_estimate', 'unknown')}",
                ],
                "variables": types.get("locals", []),
                "vulnerabilities": vuln_list,
            }
        else:  # medium
            result = self.llm.summarize_function(**context)
            return {
                "summary": result.get("summary", "No summary available."),
                "steps": [
                    result.get("behavior", ""),
                    result.get("algorithmic_intent", ""),
                ] + result.get("side_effects", []),
                "variables": [],
                "vulnerabilities": [],
            }

    def _explain_classical(self, func_addr: int, level: str) -> Dict[str, Any]:
        func_name = self._lookup_function_name(func_addr)
        blocks = self.g.fetch_basic_blocks(func_addr)
        edges = self.g.fetch_flow_edges(func_addr)

        block_insns = {bb: self.g.fetch_block_instructions(bb) for bb in blocks}
        calls = self._collect_calls(blocks)
        loops = self._detect_back_edges(blocks, edges)

        steps = []
        if blocks:
            steps.append(f"CFG has {len(blocks)} basic blocks and {len(edges)} edges.")
        if loops:
            steps.append(f"Contains {len(loops)} loop(s).")
        if calls:
            steps.append(f"Calls: {', '.join(calls)}.")

        summary = (
            f"{func_name} @ 0x{func_addr:x}: {len(blocks)} blocks, "
            f"{len(edges)} edges, {len(loops)} loop(s), {len(calls)} call(s)."
        )

        return {
            "summary": summary,
            "steps": steps,
            "variables": [],
            "vulnerabilities": self._classical_vulns(func_addr),
        }

    def _classical_name(self, func_addr: int) -> str:
        blocks = self.g.fetch_basic_blocks(func_addr)
        calls = self._collect_calls(blocks)
        if not calls:
            return f"sub_{func_addr:x}"
        return f"wrapper_{calls[0]}" if len(calls) == 1 else f"sub_{func_addr:x}"

    def _classical_variables(self, func_addr: int) -> List[Dict[str, str]]:
        blocks = self.g.fetch_basic_blocks(func_addr)
        regs = set()
        reg_pattern = re.compile(
            r"\b(r[abcd]x|r[bs]p|r[sd]i|r\d+|e[abcd]x|e[bs]p|e[sd]i)\b",
            re.IGNORECASE,
        )
        for bb in blocks:
            insns = self.g.fetch_block_instructions(bb)
            for insn in insns:
                for op in insn.get("operands", []):
                    for r in reg_pattern.findall(str(op)):
                        regs.add(r.lower())
        return [{"original": r, "suggested": r, "type_hint": "register"} for r in sorted(regs)]

    def _classical_summary(self, func_addr: int) -> Dict[str, Any]:
        func_name = self._lookup_function_name(func_addr)
        blocks = self.g.fetch_basic_blocks(func_addr)
        calls = self._collect_calls(blocks)
        return {
            "summary": f"{func_name} has {len(blocks)} block(s) and calls {', '.join(calls) if calls else 'nothing'}.",
            "behavior": "Unknown (LLM not available)",
            "side_effects": [],
            "algorithmic_intent": "Unknown",
            "complexity_estimate": "Unknown",
        }

    def _classical_vulns(self, func_addr: int) -> List[Dict[str, str]]:
        unsafe_funcs = {"strcpy", "strcat", "gets", "sprintf", "vsprintf"}
        blocks = self.g.fetch_basic_blocks(func_addr)
        vulns = []
        for bb in blocks:
            insns = self.g.fetch_block_instructions(bb)
            for insn in insns:
                mnem = (insn.get("mnemonic") or "").lower()
                ops = insn.get("operands", [])
                if mnem in ("call", "bl", "blr") and ops:
                    target = str(ops[0]).lower()
                    for uf in unsafe_funcs:
                        if uf in target:
                            vulns.append({
                                "type": "unsafe_call",
                                "severity": "medium",
                                "description": f"Call to {ops[0]} may lack bounds checking.",
                                "location": f"0x{insn.get('addr', 0):x}",
                                "recommendation": f"Consider using a safer alternative to {uf}.",
                            })
        return vulns

    # ── Helpers ────────────────────────────────────────────────────────────

    def _lookup_function_name(self, func_addr: int) -> str:
        for func in self.g.fetch_functions():
            if func.get("addr") == func_addr:
                return func.get("name", f"sub_{func_addr:x}")
        return f"sub_{func_addr:x}"

    def _collect_calls(self, blocks: List[int]) -> List[str]:
        targets = set()
        for bb in blocks:
            insns = self.g.fetch_block_instructions(bb)
            for insn in insns:
                mnem = (insn.get("mnemonic") or "").lower()
                if mnem in ("call", "bl", "blr"):
                    ops = insn.get("operands", [])
                    if ops:
                        name = str(ops[0])
                        for prefix in ("sym.imp.", "sym.", "plt."):
                            if name.startswith(prefix):
                                name = name[len(prefix):]
                        targets.add(name)
        return sorted(targets)

    def _detect_back_edges(self, blocks: List[int], edges: List) -> List:
        block_set = set(blocks)
        return [(s, d) for s, d in edges if s in block_set and d in block_set and d <= s]
