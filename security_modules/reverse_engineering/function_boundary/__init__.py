"""
Function Boundary Detection — identifies function start/end addresses.

Uses heuristic prologue/epilogue detection and call-target analysis
to identify function boundaries in stripped binaries.
"""

from typing import Any, Dict, List, Optional, Set, Tuple


class FunctionBoundaryDetector:
    """
    Detects function boundaries in binary code using pattern
    matching on common prologue/epilogue sequences and
    call-target resolution.
    """

    # Common x86-64 prologue patterns (byte prefix as mnemonic sequence)
    _PROLOGUE_PATTERNS = [
        ["push", "mov"],          # push rbp; mov rbp, rsp
        ["push", "sub"],          # push rbp; sub rsp, N
        ["sub"],                  # sub rsp, N (leaf with no frame pointer)
        ["endbr64", "push"],      # CET-enabled prologue
    ]

    # Common epilogue patterns
    _EPILOGUE_PATTERNS = [
        ["leave", "ret"],
        ["pop", "ret"],
        ["add", "ret"],           # add rsp, N; ret
        ["ret"],
    ]

    def detect_boundaries(
        self,
        graph_store,
        func_addr: int,
    ) -> Dict[str, Any]:
        """
        Analyze a known function to refine its boundary information.

        Returns start address, end address, size estimate,
        prologue/epilogue classification.
        """
        blocks = graph_store.fetch_basic_blocks(func_addr)
        if not blocks:
            return {"addr": func_addr, "start": func_addr, "end": func_addr, "size": 0}

        start = min(blocks)
        end = start

        # Find the highest instruction address to estimate function end
        for bb in blocks:
            insns = graph_store.fetch_block_instructions(bb)
            if insns:
                last_addr = insns[-1].get("addr", bb)
                if last_addr > end:
                    end = last_addr

        # Classify prologue
        entry_block = func_addr if func_addr in blocks else min(blocks)
        entry_insns = graph_store.fetch_block_instructions(entry_block)
        prologue = self._classify_prologue(entry_insns)

        # Classify epilogue
        epilogue = self._classify_epilogue(graph_store, blocks)

        return {
            "addr": func_addr,
            "start": start,
            "end": end,
            "size": end - start,
            "block_count": len(blocks),
            "prologue": prologue,
            "epilogue": epilogue,
        }

    def detect_candidates(
        self,
        graph_store,
    ) -> List[Dict[str, Any]]:
        """
        Scan all basic blocks and identify potential function starts
        that are not yet registered as functions.
        """
        known_funcs = {f.get("addr") for f in graph_store.fetch_functions()}
        candidates = []

        # Look at call targets that aren't known functions
        for func in graph_store.fetch_functions():
            addr = func.get("addr")
            if addr is None:
                continue
            blocks = graph_store.fetch_basic_blocks(addr)
            for bb in blocks:
                insns = graph_store.fetch_block_instructions(bb)
                for insn in insns:
                    mnem = (insn.get("mnemonic") or "").lower()
                    if mnem in ("call", "bl", "blr"):
                        ops = insn.get("operands") or []
                        if ops:
                            try:
                                target = int(ops[0], 0) if isinstance(ops[0], str) else int(ops[0])
                                if target not in known_funcs and target > 0:
                                    candidates.append({
                                        "addr": target,
                                        "source": "call_target",
                                        "caller": addr,
                                    })
                                    known_funcs.add(target)
                            except (ValueError, TypeError):
                                pass

        return candidates

    def _classify_prologue(self, entry_insns: List[Dict]) -> Dict[str, Any]:
        """Classify the function prologue pattern."""
        if not entry_insns:
            return {"type": "unknown", "instructions": []}

        mnemonics = [(insn.get("mnemonic") or "").lower() for insn in entry_insns[:4]]
        for pattern in self._PROLOGUE_PATTERNS:
            if len(mnemonics) >= len(pattern):
                if all(mnemonics[i].startswith(p) for i, p in enumerate(pattern)):
                    return {
                        "type": "_".join(pattern),
                        "instructions": mnemonics[:len(pattern)],
                    }

        return {"type": "non_standard", "instructions": mnemonics[:3]}

    def _classify_epilogue(self, graph_store, blocks: List[int]) -> Dict[str, Any]:
        """Classify the function epilogue pattern."""
        # Find exit blocks (blocks with no outgoing flow edges)
        all_edges = set()
        for bb in blocks:
            edges = graph_store.fetch_flow_edges_from(bb)
            block_set = set(blocks)
            for s, d in edges:
                if d in block_set:
                    all_edges.add((s, d))

        sources = {s for s, d in all_edges}
        exit_blocks = [b for b in blocks if b not in sources]

        if not exit_blocks:
            exit_blocks = [max(blocks)]

        for exit_bb in exit_blocks:
            insns = graph_store.fetch_block_instructions(exit_bb)
            if not insns:
                continue
            mnemonics = [(insn.get("mnemonic") or "").lower() for insn in insns[-3:]]
            for pattern in self._EPILOGUE_PATTERNS:
                plen = len(pattern)
                if len(mnemonics) >= plen:
                    tail = mnemonics[-plen:]
                    if all(tail[i].startswith(p) for i, p in enumerate(pattern)):
                        return {
                            "type": "_".join(pattern),
                            "exit_block": exit_bb,
                        }

        return {"type": "unknown", "exit_block": exit_blocks[0] if exit_blocks else None}
