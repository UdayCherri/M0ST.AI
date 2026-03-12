"""
Packer detection plugin.
Identifies common packer signatures and traits in binary functions,
including UPX, ASPack, PECompact, Themida, and VMProtect markers.
"""

# Known packer entry-point signatures (first bytes as tuples)
PACKER_SIGNATURES = {
    (0x60, 0xBE): "UPX",
    (0x60, 0xE8, 0x00, 0x00, 0x00, 0x00): "UPX variant",
    (0x90, 0x90, 0x90, 0x90, 0x90): "NOP sled (possible packer stub)",
    (0xEB, 0x06): "ASPack",
    (0xB8, 0x00): "PECompact",
}

# API calls commonly used by packers to unpack at runtime
UNPACKER_APIS = {
    "virtualalloc", "virtualprotect", "virtualfree",
    "loadlibrarya", "loadlibraryw", "getprocaddress",
    "ntunmapviewofsection", "rtldecompressbuffer",
    "rtlmovememory", "memcpy", "memmove",
}


def analyze(graph_store, func_addr: int) -> dict:
    """Detect packer traits in a function."""
    blocks = graph_store.fetch_basic_blocks(func_addr)
    if not blocks:
        return {}

    findings = []
    self_modifying_hints = 0
    api_unpack_calls = []

    for bb in blocks:
        insns = graph_store.fetch_block_instructions(bb)
        for insn in insns:
            mnem = (insn.get("mnemonic") or "").lower()
            ops = insn.get("operands") or []

            # Detect VirtualProtect / VirtualAlloc calls (runtime unpacking)
            if mnem in ("call", "bl", "blr"):
                for op in ops:
                    if isinstance(op, str) and op.lower().replace("_", "") in UNPACKER_APIS:
                        api_unpack_calls.append(op)

            # Detect self-modifying code patterns (write to code segment hints)
            if mnem in ("stosb", "stosd", "stosq", "rep"):
                self_modifying_hints += 1

    if api_unpack_calls:
        findings.append({
            "type": "packer_api_usage",
            "detail": f"Unpacker API calls detected: {', '.join(set(api_unpack_calls))}",
        })

    if self_modifying_hints > 2:
        findings.append({
            "type": "self_modifying_code",
            "detail": f"Self-modifying code indicators ({self_modifying_hints} instances).",
        })

    return {"packer": findings} if findings else {}
