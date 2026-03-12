"""
Struct Recovery — reconstructs composite data type layouts.

Analyzes memory access patterns to recover struct/class field
layouts, sizes, and alignments from binary code.
"""

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple


class StructRecovery:
    """
    Recovers struct layouts from memory access patterns
    observed in function disassembly.
    """

    def recover_structs(
        self,
        graph_store,
        func_addr: int,
    ) -> List[Dict[str, Any]]:
        """
        Analyze memory access patterns in a function to recover
        potential struct layouts.
        """
        blocks = graph_store.fetch_basic_blocks(func_addr)
        accesses = self._collect_accesses(graph_store, blocks)

        if not accesses:
            return []

        # Group by base register
        groups = defaultdict(list)
        for acc in accesses:
            groups[acc["base"]].append(acc)

        structs = []
        for base, group in groups.items():
            offsets = sorted(set(a["offset"] for a in group))
            if len(offsets) < 2:
                continue

            fields = []
            for i, off in enumerate(offsets):
                next_off = offsets[i + 1] if i + 1 < len(offsets) else off + 8
                field_size = min(next_off - off, 8)
                width = self._infer_field_width(group, off)
                fields.append({
                    "offset": off,
                    "name": f"field_{off:x}",
                    "type": self._width_to_type(width or field_size),
                    "size": max(width or field_size, 1),
                })

            structs.append({
                "name": f"struct_{base}_{func_addr:x}",
                "base_register": base,
                "func_addr": func_addr,
                "size": max(offsets) + 8,
                "fields": fields,
            })

        return structs

    def _collect_accesses(
        self, graph_store, blocks: List[int]
    ) -> List[Dict[str, Any]]:
        """Extract structured memory access info from instructions."""
        accesses = []
        pattern = re.compile(r"\[(\w+)\s*[+\-]\s*(0x[0-9a-fA-F]+|\d+)\]")

        for bb in blocks:
            insns = graph_store.fetch_block_instructions(bb)
            for insn in insns:
                mnem = (insn.get("mnemonic") or "").lower()
                for op in insn.get("operands", []):
                    match = pattern.search(str(op))
                    if match:
                        base = match.group(1).lower()
                        try:
                            offset = int(match.group(2), 0)
                        except ValueError:
                            continue
                        accesses.append({
                            "base": base,
                            "offset": offset,
                            "mnemonic": mnem,
                            "addr": insn.get("addr", bb),
                            "operand": str(op),
                        })
        return accesses

    def _infer_field_width(self, accesses: List[Dict], offset: int) -> Optional[int]:
        """Infer field width from instruction context at a given offset."""
        for acc in accesses:
            if acc["offset"] != offset:
                continue
            op = acc["operand"].lower()
            if "byte" in op:
                return 1
            if "word" in op and "dword" not in op and "qword" not in op:
                return 2
            if "dword" in op:
                return 4
            if "qword" in op:
                return 8
        return None

    @staticmethod
    def _width_to_type(width: int) -> str:
        return {1: "uint8_t", 2: "uint16_t", 4: "uint32_t", 8: "uint64_t"}.get(width, "unknown")
