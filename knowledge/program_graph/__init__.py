"""
Program Knowledge Graph (PKG) — Central representation for M0ST.

The PKG is the unified data structure through which all modules communicate.
It stores the complete program representation recovered by the Reverse
Engineering module and is consumed by downstream analysis modules.

Node types:
    - Function: recovered function with name, address, signature
    - BasicBlock: a contiguous sequence of instructions
    - Instruction: a single machine instruction
    - Variable: recovered local/global variable
    - Struct: recovered composite data type

Edge types:
    - CALL: inter-procedural call relationship
    - CFG_FLOW: intra-procedural control-flow edge
    - DATA_FLOW: data dependency between instructions/variables
    - TYPE_RELATION: type linkage (variable→struct, parameter→type)
"""

from __future__ import annotations

import json
from collections import defaultdict
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple


# ── Node & Edge type enumerations ──────────────────────────────────────────

class NodeType(Enum):
    FUNCTION = auto()
    BASIC_BLOCK = auto()
    INSTRUCTION = auto()
    VARIABLE = auto()
    STRUCT = auto()
    STRING = auto()
    IMPORT = auto()
    EMBEDDING = auto()


class EdgeType(Enum):
    CALL = auto()
    CFG_FLOW = auto()
    DATA_FLOW = auto()
    TYPE_RELATION = auto()
    USES_STRING = auto()
    IMPORTS = auto()
    TYPE_OF = auto()
    SIMILAR_TO = auto()


# ── PKG Implementation ────────────────────────────────────────────────────

class ProgramKnowledgeGraph:
    """
    In-memory Program Knowledge Graph.

    All reverse-engineering and analysis modules read/write through this
    graph, ensuring a single source of truth for the recovered program.
    """

    def __init__(self):
        # ── Node stores ────────────────────────────────────────────────
        self._functions: Dict[int, Dict[str, Any]] = {}
        self._basic_blocks: Dict[int, Dict[str, Any]] = {}
        self._instructions: Dict[int, Dict[str, Any]] = {}
        self._variables: Dict[str, Dict[str, Any]] = {}  # key = unique id
        self._structs: Dict[str, Dict[str, Any]] = {}    # key = struct name
        self._strings: Dict[str, Dict[str, Any]] = {}    # key = address or unique id
        self._imports: Dict[str, Dict[str, Any]] = {}    # key = import name
        self._embeddings: Dict[str, Dict[str, Any]] = {}  # key = entity id

        # ── Edge stores ────────────────────────────────────────────────
        self._call_edges: Set[Tuple[int, int]] = set()
        self._cfg_flow_edges: Set[Tuple[int, int]] = set()
        self._data_flow_edges: List[Dict[str, Any]] = []
        self._type_relations: List[Dict[str, Any]] = []
        self._uses_string_edges: List[Tuple[str, str]] = []   # (func/insn id, string id)
        self._imports_edges: List[Tuple[str, str]] = []        # (func id, import name)
        self._type_of_edges: List[Tuple[str, str]] = []        # (entity id, type name)
        self._similar_to_edges: List[Dict[str, Any]] = []      # {src, dst, score}

        # ── Relationship indexes ───────────────────────────────────────
        self._func_to_blocks: Dict[int, Set[int]] = defaultdict(set)
        self._block_to_insns: Dict[int, Set[int]] = defaultdict(set)

        # ── Dynamic trace data ─────────────────────────────────────────
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._runtime_flow: List[Dict] = []
        self._executes: List[Dict] = []
        self._syscall_events: List[Dict] = []
        self._suspect_edges: Set[Tuple[int, int]] = set()

        # ── Metadata ───────────────────────────────────────────────────
        self._verification_results: Optional[Dict] = None
        self._semantic_summaries: Optional[Dict] = None
        self._annotations: Dict[str, Dict[str, Any]] = {}

    # ════════════════════════════════════════════════════════════════════
    # Function nodes
    # ════════════════════════════════════════════════════════════════════

    def add_function(self, name: str, addr: int, **props):
        self._functions[addr] = {"name": name, "addr": addr, **props}

    def get_function(self, addr: int) -> Optional[Dict[str, Any]]:
        return self._functions.get(addr)

    def fetch_functions(self) -> List[Dict]:
        return sorted(self._functions.values(), key=lambda f: f["addr"])

    def set_function_properties(self, func_addr: int, props: Dict):
        if func_addr in self._functions:
            self._functions[func_addr].update(props)

    # Backward compat aliases
    create_function = add_function

    # ════════════════════════════════════════════════════════════════════
    # Basic Block nodes
    # ════════════════════════════════════════════════════════════════════

    def add_basic_block(self, func_addr: int, bb_addr: int, **props):
        self._basic_blocks[bb_addr] = {"addr": bb_addr, **props}
        self._func_to_blocks[func_addr].add(bb_addr)

    def fetch_basic_blocks(self, func_addr: int) -> List[int]:
        return sorted(self._func_to_blocks.get(func_addr, set()))

    def fetch_all_basic_blocks(self) -> List[int]:
        return sorted(self._basic_blocks.keys())

    # Backward compat alias
    create_basic_block = add_basic_block

    # ════════════════════════════════════════════════════════════════════
    # Instruction nodes
    # ════════════════════════════════════════════════════════════════════

    def add_instruction(self, bb_addr: int, addr: int, mnemonic: str, operands: List[str]):
        self._instructions[addr] = {
            "addr": addr,
            "mnemonic": mnemonic,
            "operands": list(operands),
        }
        self._block_to_insns[bb_addr].add(addr)

    def fetch_block_instructions(self, bb_addr: int) -> List[Dict]:
        insn_addrs = self._block_to_insns.get(bb_addr, set())
        return sorted(
            [self._instructions[a] for a in insn_addrs if a in self._instructions],
            key=lambda i: i["addr"],
        )

    # Backward compat alias
    create_instruction = add_instruction

    # ════════════════════════════════════════════════════════════════════
    # Variable nodes
    # ════════════════════════════════════════════════════════════════════

    def add_variable(self, var_id: str, name: str, var_type: str = "unknown",
                     func_addr: Optional[int] = None, **props):
        self._variables[var_id] = {
            "id": var_id,
            "name": name,
            "type": var_type,
            "func_addr": func_addr,
            **props,
        }

    def get_variable(self, var_id: str) -> Optional[Dict[str, Any]]:
        return self._variables.get(var_id)

    def fetch_variables(self, func_addr: Optional[int] = None) -> List[Dict]:
        if func_addr is None:
            return list(self._variables.values())
        return [v for v in self._variables.values() if v.get("func_addr") == func_addr]

    # ════════════════════════════════════════════════════════════════════
    # Struct nodes
    # ════════════════════════════════════════════════════════════════════

    def add_struct(self, name: str, fields: Optional[List[Dict]] = None, size: int = 0):
        self._structs[name] = {
            "name": name,
            "fields": fields or [],
            "size": size,
        }

    def get_struct(self, name: str) -> Optional[Dict[str, Any]]:
        return self._structs.get(name)

    def fetch_structs(self) -> List[Dict]:
        return list(self._structs.values())

    # ════════════════════════════════════════════════════════════════════
    # String nodes
    # ════════════════════════════════════════════════════════════════════

    def add_string(self, string_id: str, value: str, addr: Optional[int] = None,
                   encoding: str = "utf-8", **props):
        self._strings[string_id] = {
            "id": string_id, "value": value, "addr": addr,
            "encoding": encoding, **props,
        }

    def get_string(self, string_id: str) -> Optional[Dict[str, Any]]:
        return self._strings.get(string_id)

    def fetch_strings(self) -> List[Dict]:
        return list(self._strings.values())

    def search_strings(self, pattern: str) -> List[Dict]:
        import re as _re
        try:
            rx = _re.compile(pattern, _re.IGNORECASE)
        except _re.error:
            return []
        return [s for s in self._strings.values() if rx.search(s.get("value", ""))]

    # ════════════════════════════════════════════════════════════════════
    # Import nodes
    # ════════════════════════════════════════════════════════════════════

    def add_import(self, name: str, library: str = "", ordinal: Optional[int] = None,
                   addr: Optional[int] = None, **props):
        self._imports[name] = {
            "name": name, "library": library, "ordinal": ordinal,
            "addr": addr, **props,
        }

    def get_import(self, name: str) -> Optional[Dict[str, Any]]:
        return self._imports.get(name)

    def fetch_imports(self) -> List[Dict]:
        return sorted(self._imports.values(), key=lambda i: i.get("name", ""))

    # ════════════════════════════════════════════════════════════════════
    # CALL edges
    # ════════════════════════════════════════════════════════════════════

    def add_call_edge(self, caller: int, callee: int):
        self._call_edges.add((caller, callee))

    def fetch_call_edges(self) -> List[Tuple[int, int]]:
        return sorted(self._call_edges)

    def fetch_callees(self, func_addr: int) -> List[int]:
        return sorted(d for s, d in self._call_edges if s == func_addr)

    def fetch_callers(self, func_addr: int) -> List[int]:
        return sorted(s for s, d in self._call_edges if d == func_addr)

    # ════════════════════════════════════════════════════════════════════
    # CFG_FLOW edges
    # ════════════════════════════════════════════════════════════════════

    def add_flow_edge(self, src_bb: int, dst_bb: int):
        self._cfg_flow_edges.add((src_bb, dst_bb))

    def fetch_flow_edges(self, func_addr: int) -> List[Tuple[int, int]]:
        block_set = self._func_to_blocks.get(func_addr, set())
        return sorted(
            (s, d) for s, d in self._cfg_flow_edges
            if s in block_set and d in block_set
        )

    def fetch_all_flow_edges(self) -> List[Tuple[int, int]]:
        return sorted(self._cfg_flow_edges)

    def fetch_flow_edges_from(self, src_bb: int) -> List[Tuple[int, int]]:
        return sorted((s, d) for s, d in self._cfg_flow_edges if s == src_bb)

    def remove_flow_edge(self, src_bb: int, dst_bb: int):
        self._cfg_flow_edges.discard((src_bb, dst_bb))

    # ════════════════════════════════════════════════════════════════════
    # DATA_FLOW edges
    # ════════════════════════════════════════════════════════════════════

    def add_data_flow(self, src: str, dst: str, flow_type: str = "def-use", **props):
        self._data_flow_edges.append({
            "src": src, "dst": dst, "type": flow_type, **props,
        })

    def fetch_data_flows(self, entity_id: Optional[str] = None) -> List[Dict]:
        if entity_id is None:
            return list(self._data_flow_edges)
        return [e for e in self._data_flow_edges
                if e["src"] == entity_id or e["dst"] == entity_id]

    # ════════════════════════════════════════════════════════════════════
    # TYPE_RELATION edges
    # ════════════════════════════════════════════════════════════════════

    def add_type_relation(self, entity: str, type_name: str, relation: str = "has_type"):
        self._type_relations.append({
            "entity": entity, "type_name": type_name, "relation": relation,
        })

    def fetch_type_relations(self, entity: Optional[str] = None) -> List[Dict]:
        if entity is None:
            return list(self._type_relations)
        return [r for r in self._type_relations if r["entity"] == entity]

    # ════════════════════════════════════════════════════════════════════
    # USES_STRING edges
    # ════════════════════════════════════════════════════════════════════

    def add_uses_string(self, entity_id: str, string_id: str):
        self._uses_string_edges.append((entity_id, string_id))

    def fetch_uses_string(self, entity_id: Optional[str] = None) -> List[Tuple[str, str]]:
        if entity_id is None:
            return list(self._uses_string_edges)
        return [(e, s) for e, s in self._uses_string_edges if e == entity_id]

    # ════════════════════════════════════════════════════════════════════
    # IMPORTS edges
    # ════════════════════════════════════════════════════════════════════

    def add_imports_edge(self, func_id: str, import_name: str):
        self._imports_edges.append((func_id, import_name))

    def fetch_imports_edges(self, func_id: Optional[str] = None) -> List[Tuple[str, str]]:
        if func_id is None:
            return list(self._imports_edges)
        return [(f, i) for f, i in self._imports_edges if f == func_id]

    # ════════════════════════════════════════════════════════════════════
    # TYPE_OF edges
    # ════════════════════════════════════════════════════════════════════

    def add_type_of(self, entity_id: str, type_name: str):
        self._type_of_edges.append((entity_id, type_name))

    def fetch_type_of(self, entity_id: Optional[str] = None) -> List[Tuple[str, str]]:
        if entity_id is None:
            return list(self._type_of_edges)
        return [(e, t) for e, t in self._type_of_edges if e == entity_id]

    # ════════════════════════════════════════════════════════════════════
    # Embedding nodes
    # ════════════════════════════════════════════════════════════════════

    def add_embedding(self, entity_id: str, vector: List[float],
                      model: str = "gnn", **props):
        self._embeddings[entity_id] = {
            "entity_id": entity_id, "vector": vector,
            "model": model, "dim": len(vector), **props,
        }

    def get_embedding(self, entity_id: str) -> Optional[Dict[str, Any]]:
        return self._embeddings.get(entity_id)

    def fetch_embeddings(self) -> List[Dict]:
        return list(self._embeddings.values())

    # ════════════════════════════════════════════════════════════════════
    # SIMILAR_TO edges
    # ════════════════════════════════════════════════════════════════════

    def add_similar_to(self, src: str, dst: str, score: float, **props):
        self._similar_to_edges.append({
            "src": src, "dst": dst, "score": score, **props,
        })

    def fetch_similar_to(self, entity_id: Optional[str] = None) -> List[Dict]:
        if entity_id is None:
            return list(self._similar_to_edges)
        return [e for e in self._similar_to_edges
                if e["src"] == entity_id or e["dst"] == entity_id]

    # ════════════════════════════════════════════════════════════════════
    # Heuristics / Properties (backward compat with old MemoryGraphStore)
    # ════════════════════════════════════════════════════════════════════

    def mark_loop_header(self, bb_addr: int, loop_body=None, back_edges=None,
                         loop_depth=None, crypto_constant_time=None):
        if bb_addr in self._basic_blocks:
            self._basic_blocks[bb_addr].update({
                "loop_header": True,
                "loop_body": loop_body,
                "loop_back_edges": back_edges,
                "loop_depth": loop_depth,
                "crypto_constant_time": crypto_constant_time,
            })

    def set_plugin_facts(self, func_addr: int, facts: Dict):
        if func_addr in self._functions:
            self._functions[func_addr]["plugin_facts"] = json.dumps(facts)

    def set_switch_info(self, func_addr: int, header_bb: int, cases: List[int]):
        if header_bb in self._basic_blocks:
            self._basic_blocks[header_bb].update({
                "switch_header": True,
                "switch_cases": cases,
            })

    # ════════════════════════════════════════════════════════════════════
    # Dynamic tracing (backward compat)
    # ════════════════════════════════════════════════════════════════════

    def create_run(self, run_id: str, binary_path: str):
        self._runs[run_id] = {"id": run_id, "binary_path": binary_path}

    def get_latest_run(self) -> Optional[Dict]:
        if not self._runs:
            return None
        return list(self._runs.values())[-1]

    def add_executes_edge(self, run_id: str, bb_addr: int, seq: int,
                          pc: int, next_pc: int, regs: Dict):
        self._executes.append({
            "run_id": run_id, "bb_addr": bb_addr, "seq": seq,
            "pc": pc, "next_pc": next_pc, "regs": regs,
        })

    def add_runtime_flow(self, run_id: str, src_bb: int, dst_bb: int,
                         seq: int, pc: int, next_pc: int, regs: Dict):
        self._runtime_flow.append({
            "run_id": run_id, "src_bb": src_bb, "dst_bb": dst_bb,
            "seq": seq, "pc": pc, "next_pc": next_pc, "regs": regs,
        })

    def add_syscall_event(self, run_id: str, seq: int, pc: int,
                          syscall_number: int, args: List):
        safe_args = [a if isinstance(a, int) else 0 for a in args if a is not None]
        self._syscall_events.append({
            "run_id": run_id, "seq": seq, "pc": pc,
            "syscall_number": syscall_number, "args": safe_args,
        })

    def fetch_runtime_flow_edges(self) -> List[Tuple[int, int]]:
        seen: Set[Tuple[int, int]] = set()
        for entry in self._runtime_flow:
            seen.add((entry["src_bb"], entry["dst_bb"]))
        return sorted(seen)

    def fetch_executed_blocks(self) -> List[int]:
        seen: Set[int] = set()
        for entry in self._executes:
            seen.add(entry["bb_addr"])
        return sorted(seen)

    def mark_flow_edge_suspect(self, src_bb: int, dst_bb: int):
        self._suspect_edges.add((src_bb, dst_bb))

    # ════════════════════════════════════════════════════════════════════
    # Verification / Semantic metadata
    # ════════════════════════════════════════════════════════════════════

    def set_verification_results(self, results: Dict):
        self._verification_results = results

    def get_verification_results(self) -> Optional[Dict]:
        return self._verification_results

    def set_semantic_summaries(self, summaries: Dict):
        self._semantic_summaries = summaries

    def get_semantic_summaries(self) -> Optional[Dict]:
        return self._semantic_summaries

    # ════════════════════════════════════════════════════════════════════
    # Annotations (plugin/analysis enrichment)
    # ════════════════════════════════════════════════════════════════════

    def annotate(self, entity_id: str, key: str, value: Any):
        self._annotations.setdefault(entity_id, {})[key] = value

    def get_annotations(self, entity_id: str) -> Dict[str, Any]:
        return self._annotations.get(entity_id, {})

    # ════════════════════════════════════════════════════════════════════
    # Graph-wide operations
    # ════════════════════════════════════════════════════════════════════

    def clear(self):
        """Reset the entire graph."""
        self._functions.clear()
        self._basic_blocks.clear()
        self._instructions.clear()
        self._variables.clear()
        self._structs.clear()
        self._strings.clear()
        self._imports.clear()
        self._embeddings.clear()
        self._call_edges.clear()
        self._cfg_flow_edges.clear()
        self._data_flow_edges.clear()
        self._type_relations.clear()
        self._uses_string_edges.clear()
        self._imports_edges.clear()
        self._type_of_edges.clear()
        self._similar_to_edges.clear()
        self._func_to_blocks.clear()
        self._block_to_insns.clear()
        self._runs.clear()
        self._runtime_flow.clear()
        self._executes.clear()
        self._syscall_events.clear()
        self._suspect_edges.clear()
        self._verification_results = None
        self._semantic_summaries = None
        self._annotations.clear()

    # Backward compat alias
    clear_graph = clear

    def summary(self) -> Dict[str, int]:
        return {
            "functions": len(self._functions),
            "basic_blocks": len(self._basic_blocks),
            "instructions": len(self._instructions),
            "variables": len(self._variables),
            "structs": len(self._structs),
            "strings": len(self._strings),
            "imports": len(self._imports),
            "embeddings": len(self._embeddings),
            "call_edges": len(self._call_edges),
            "cfg_flow_edges": len(self._cfg_flow_edges),
            "data_flow_edges": len(self._data_flow_edges),
            "type_relations": len(self._type_relations),
            "uses_string_edges": len(self._uses_string_edges),
            "imports_edges": len(self._imports_edges),
            "type_of_edges": len(self._type_of_edges),
            "similar_to_edges": len(self._similar_to_edges),
        }

    def export_json(self) -> Dict[str, Any]:
        """Export the entire PKG as a JSON-serializable dict."""
        return {
            "functions": {f"0x{a:x}": d for a, d in self._functions.items()},
            "basic_blocks": {f"0x{a:x}": d for a, d in self._basic_blocks.items()},
            "variables": self._variables,
            "structs": self._structs,
            "strings": self._strings,
            "imports": self._imports,
            "call_edges": [{"src": s, "dst": d} for s, d in self._call_edges],
            "cfg_flow_edges": [{"src": s, "dst": d} for s, d in self._cfg_flow_edges],
            "data_flow_edges": self._data_flow_edges,
            "type_relations": self._type_relations,
            "uses_string_edges": [{"entity": e, "string": s} for e, s in self._uses_string_edges],
            "imports_edges": [{"func": f, "import": i} for f, i in self._imports_edges],
            "type_of_edges": [{"entity": e, "type": t} for e, t in self._type_of_edges],
            "embeddings": self._embeddings,
            "similar_to_edges": self._similar_to_edges,
            "summary": self.summary(),
        }

    def close(self):
        pass

    def session(self):
        return None
