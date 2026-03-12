"""
Loop pattern detection plugin.
Identifies loop structures (counted loops, memcpy-style, hash accumulation)
by analysing back-edges and register-usage patterns within basic blocks.
"""


def analyze(graph_store, func_addr: int) -> dict:
    """Detect loop patterns in a function's CFG."""
    blocks = graph_store.fetch_basic_blocks(func_addr)
    edges = graph_store.fetch_flow_edges(func_addr)
    if not blocks or not edges:
        return {}

    block_set = set(blocks)
    sorted_blocks = sorted(blocks)
    block_order = {addr: i for i, addr in enumerate(sorted_blocks)}

    # Identify back-edges (target dominates source in linear layout)
    back_edges = []
    for src, dst in edges:
        if src in block_order and dst in block_order:
            if block_order[dst] <= block_order[src]:
                back_edges.append((src, dst))

    if not back_edges:
        return {}

    findings = []

    for src, loop_head in back_edges:
        # Collect blocks in the loop body (between head and latch)
        head_idx = block_order[loop_head]
        latch_idx = block_order[src]
        loop_body = [b for b in sorted_blocks if head_idx <= block_order[b] <= latch_idx]

        total_insns = 0
        has_counter = False
        has_memop = False
        has_accumulator = False

        for bb in loop_body:
            insns = graph_store.fetch_block_instructions(bb)
            for insn in insns:
                total_insns += 1
                mnem = (insn.get("mnemonic") or "").lower()

                if mnem in ("inc", "dec", "add", "sub"):
                    ops = insn.get("operands") or []
                    if ops and isinstance(ops[0], str):
                        reg = ops[0].lower()
                        if reg in ("ecx", "rcx", "esi", "rsi", "edi", "rdi", "r8", "r9"):
                            has_counter = True

                if mnem in ("stosb", "stosd", "stosq", "movsb", "movsd", "movsq",
                            "rep", "lodsb", "lodsd"):
                    has_memop = True

                if mnem in ("xor", "add", "adc", "rol", "ror"):
                    has_accumulator = True

        loop_type = "generic_loop"
        if has_memop:
            loop_type = "memcpy_style_loop"
        elif has_counter and has_accumulator:
            loop_type = "hash_accumulation_loop"
        elif has_counter:
            loop_type = "counted_loop"

        findings.append({
            "type": loop_type,
            "loop_head": loop_head,
            "latch_block": src,
            "body_blocks": len(loop_body),
            "instruction_count": total_insns,
        })

    return {"loops": findings} if findings else {}
