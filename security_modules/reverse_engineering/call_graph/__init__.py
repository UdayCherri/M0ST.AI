"""
Call Graph Generation — builds inter-procedural call graphs.

Extracts call relationships between functions and stores them
as CALL edges in the Program Knowledge Graph.
"""

from typing import Any, Dict, List, Set, Tuple


class CallGraphBuilder:
    """
    Builds a call graph from disassembly data by resolving
    call instruction targets to known function addresses.
    """

    def build_call_graph(
        self,
        graph_store,
    ) -> Dict[str, Any]:
        """
        Scan all functions' instructions for call targets and
        create CALL edges in the graph store.

        Returns summary statistics.
        """
        functions = graph_store.fetch_functions()
        func_addrs = {f.get("addr") for f in functions if f.get("addr") is not None}
        func_names = {}
        for f in functions:
            addr = f.get("addr")
            name = f.get("name", "")
            if addr is not None:
                func_names[addr] = name
                if name:
                    func_names[name] = addr

        edges_added = 0
        unresolved = []

        for func in functions:
            caller = func.get("addr")
            if caller is None:
                continue

            blocks = graph_store.fetch_basic_blocks(caller)
            for bb in blocks:
                insns = graph_store.fetch_block_instructions(bb)
                for insn in insns:
                    mnem = (insn.get("mnemonic") or "").lower()
                    if mnem not in ("call", "bl", "blr"):
                        continue
                    ops = insn.get("operands") or []
                    if not ops:
                        continue

                    target = self._resolve_target(ops[0], func_addrs, func_names)
                    if target is not None and target != caller:
                        graph_store.add_call_edge(caller, target)
                        edges_added += 1
                    else:
                        unresolved.append({
                            "caller": caller,
                            "instruction_addr": insn.get("addr", bb),
                            "operand": ops[0],
                        })

        return {
            "total_functions": len(functions),
            "call_edges": edges_added,
            "unresolved_calls": len(unresolved),
        }

    def get_call_chain(
        self,
        graph_store,
        func_addr: int,
        depth: int = 5,
    ) -> List[List[int]]:
        """
        Extract call chains starting from a function up to a given depth.
        Returns list of chains (each chain is a list of function addresses).
        """
        chains = []
        self._walk_calls(graph_store, [func_addr], depth, chains)
        return chains

    def get_reverse_call_chain(
        self,
        graph_store,
        func_addr: int,
        depth: int = 5,
    ) -> List[List[int]]:
        """
        Extract reverse call chains (who calls this function) up to depth.
        """
        chains = []
        self._walk_callers(graph_store, [func_addr], depth, chains)
        return chains

    def _walk_calls(self, graph_store, chain: List[int], depth: int,
                    result: List[List[int]]):
        if depth <= 0:
            result.append(list(chain))
            return

        callees = graph_store.fetch_callees(chain[-1])
        if not callees:
            result.append(list(chain))
            return

        for callee in callees:
            if callee not in chain:  # avoid cycles
                chain.append(callee)
                self._walk_calls(graph_store, chain, depth - 1, result)
                chain.pop()

    def _walk_callers(self, graph_store, chain: List[int], depth: int,
                      result: List[List[int]]):
        if depth <= 0:
            result.append(list(chain))
            return

        callers = graph_store.fetch_callers(chain[-1])
        if not callers:
            result.append(list(chain))
            return

        for caller in callers:
            if caller not in chain:
                chain.append(caller)
                self._walk_callers(graph_store, chain, depth - 1, result)
                chain.pop()

    def _resolve_target(self, operand: str, func_addrs: Set[int],
                        func_names: Dict) -> int | None:
        """Resolve a call operand to a known function address."""
        # Strip symbolic prefixes
        name = str(operand)
        for prefix in ("sym.imp.", "sym.", "plt.", "reloc."):
            if name.startswith(prefix):
                name = name[len(prefix):]

        # Try direct address
        try:
            addr = int(name, 0) if isinstance(name, str) else int(name)
            if addr in func_addrs:
                return addr
        except (ValueError, TypeError):
            pass

        # Try name lookup
        if name in func_names:
            val = func_names[name]
            if isinstance(val, int):
                return val

        return None
