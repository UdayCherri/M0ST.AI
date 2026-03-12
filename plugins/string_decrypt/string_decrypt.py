"""
String decryption heuristics plugin.
Detects common inline string decryption patterns (XOR loops, RC4-style,
single-byte XOR, stack strings) and attempts to recover plaintext.
"""


def _try_xor_decode(data: list, key: int) -> str:
    """Attempt single-byte XOR decode, return printable result or empty."""
    decoded = bytes(b ^ key for b in data)
    try:
        text = decoded.decode("ascii", errors="strict")
        if all(32 <= c < 127 or c in (0, 9, 10, 13) for c in decoded):
            return text.rstrip("\x00")
    except (UnicodeDecodeError, ValueError):
        pass
    return ""


def analyze(graph_store, func_addr: int) -> dict:
    """Detect string decryption patterns in a function."""
    blocks = graph_store.fetch_basic_blocks(func_addr)
    if not blocks:
        return {}

    findings = []
    xor_sequences = []  # track consecutive XOR operand bytes
    stack_string_chars = []

    for bb in blocks:
        insns = graph_store.fetch_block_instructions(bb)
        for insn in insns:
            mnem = (insn.get("mnemonic") or "").lower()
            ops = insn.get("operands") or []

            # Detect XOR with immediate byte (common single-byte XOR decryption)
            if mnem == "xor" and len(ops) >= 2:
                try:
                    val = int(ops[-1], 0) if isinstance(ops[-1], str) else None
                    if val is not None and 1 <= val <= 0xFF:
                        xor_sequences.append(val)
                except (ValueError, TypeError):
                    pass

            # Detect stack string construction (mov byte [esp+N], imm8)
            if mnem == "mov" and len(ops) >= 2:
                target = str(ops[0]).lower()
                if "esp" in target or "rbp" in target or "rsp" in target:
                    try:
                        val = int(ops[-1], 0) if isinstance(ops[-1], str) else None
                        if val is not None and 0x20 <= val <= 0x7E:
                            stack_string_chars.append(chr(val))
                    except (ValueError, TypeError):
                        pass

    if len(xor_sequences) >= 4:
        findings.append({
            "type": "xor_decryption_loop",
            "detail": f"Repeated XOR operations detected ({len(xor_sequences)} instances), "
                      f"likely inline string decryption.",
            "xor_keys": list(set(xor_sequences)),
        })

    if len(stack_string_chars) >= 4:
        recovered = "".join(stack_string_chars)
        findings.append({
            "type": "stack_string",
            "detail": f"Stack string construction detected: \"{recovered}\"",
            "value": recovered,
        })

    return {"string_decryption": findings} if findings else {}
