"""
Unsafe Pattern Detection — detects security-relevant code patterns.

Identifies patterns such as insecure API usage, missing bounds checks,
hardcoded credentials, and other security anti-patterns in binary code.
"""

import re
from typing import Any, Dict, List


class UnsafePatternDetector:
    """
    Detects unsafe coding patterns in binary functions by examining
    instruction sequences and API call patterns from the PKG.
    """

    # Hardcoded credential indicators
    _CREDENTIAL_PATTERNS = [
        re.compile(r"password", re.IGNORECASE),
        re.compile(r"secret", re.IGNORECASE),
        re.compile(r"api[_-]?key", re.IGNORECASE),
        re.compile(r"token", re.IGNORECASE),
        re.compile(r"auth", re.IGNORECASE),
    ]

    def __init__(self, graph_store=None):
        self.g = graph_store

    # Insecure random functions
    _INSECURE_RANDOM = {"rand", "srand", "random", "srandom"}

    # Deprecated / weak crypto
    _WEAK_CRYPTO = {"MD5", "MD5_Init", "SHA1", "SHA1_Init", "DES_ecb_encrypt", "RC4"}

    def detect(
        self,
        graph_store,
        func_addr: int,
    ) -> Dict[str, Any]:
        """
        Run all unsafe pattern checks on a function.
        """
        blocks = graph_store.fetch_basic_blocks(func_addr)
        block_insns = {
            bb: graph_store.fetch_block_instructions(bb) for bb in blocks
        }

        findings = []
        findings.extend(self._check_insecure_random(block_insns))
        findings.extend(self._check_weak_crypto(block_insns))
        findings.extend(self._check_hardcoded_credentials(graph_store, func_addr))
        findings.extend(self._check_unchecked_return(block_insns))

        return {
            "func_addr": func_addr,
            "pattern_count": len(findings),
            "patterns": findings,
        }

    def _check_insecure_random(
        self, block_insns: Dict[int, List[Dict]]
    ) -> List[Dict[str, Any]]:
        findings = []
        for bb, insns in block_insns.items():
            for insn in insns:
                mnem = (insn.get("mnemonic") or "").lower()
                if mnem not in ("call", "bl"):
                    continue
                ops = insn.get("operands") or []
                if not ops:
                    continue
                target = self._strip_prefix(ops[0])
                if target in self._INSECURE_RANDOM:
                    findings.append({
                        "type": "insecure_random",
                        "severity": "medium",
                        "location": f"0x{insn.get('addr', bb):x}",
                        "description": f"Use of insecure PRNG: {target}()",
                        "recommendation": "Use a cryptographically secure RNG.",
                    })
        return findings

    def _check_weak_crypto(
        self, block_insns: Dict[int, List[Dict]]
    ) -> List[Dict[str, Any]]:
        findings = []
        for bb, insns in block_insns.items():
            for insn in insns:
                mnem = (insn.get("mnemonic") or "").lower()
                if mnem not in ("call", "bl"):
                    continue
                ops = insn.get("operands") or []
                if not ops:
                    continue
                target = self._strip_prefix(ops[0])
                if target in self._WEAK_CRYPTO:
                    findings.append({
                        "type": "weak_crypto",
                        "severity": "medium",
                        "location": f"0x{insn.get('addr', bb):x}",
                        "description": f"Use of deprecated/weak crypto: {target}",
                        "recommendation": "Use modern cryptographic primitives.",
                    })
        return findings

    def _check_hardcoded_credentials(
        self, graph_store, func_addr: int
    ) -> List[Dict[str, Any]]:
        findings = []
        # Check strings referenced by this function via PKG
        if hasattr(graph_store, "fetch_uses_string"):
            func_id = f"0x{func_addr:x}"
            string_refs = graph_store.fetch_uses_string(func_id)
            for _, string_id in string_refs:
                s = graph_store.get_string(string_id)
                if s:
                    value = s.get("value", "")
                    for pattern in self._CREDENTIAL_PATTERNS:
                        if pattern.search(value):
                            findings.append({
                                "type": "hardcoded_credential",
                                "severity": "high",
                                "description": f"Possible hardcoded credential in string: '{value[:40]}...'",
                                "recommendation": "Move secrets to environment variables or secure storage.",
                            })
                            break
        return findings

    def _check_unchecked_return(
        self, block_insns: Dict[int, List[Dict]]
    ) -> List[Dict[str, Any]]:
        """Detect calls whose return value isn't checked."""
        findings = []
        critical_calls = {"malloc", "calloc", "realloc", "fopen", "open", "socket"}

        for bb, insns in block_insns.items():
            for i, insn in enumerate(insns):
                mnem = (insn.get("mnemonic") or "").lower()
                if mnem not in ("call", "bl"):
                    continue
                ops = insn.get("operands") or []
                if not ops:
                    continue
                target = self._strip_prefix(ops[0])
                if target not in critical_calls:
                    continue

                # Check if next instruction uses/tests rax (return value)
                if i + 1 < len(insns):
                    next_insn = insns[i + 1]
                    next_mnem = (next_insn.get("mnemonic") or "").lower()
                    next_ops = " ".join(str(o) for o in (next_insn.get("operands") or []))
                    if next_mnem in ("test", "cmp") and "rax" in next_ops.lower():
                        continue
                    if next_mnem in ("mov", "lea") and "rax" in next_ops.lower():
                        continue

                findings.append({
                    "type": "unchecked_return",
                    "severity": "low",
                    "location": f"0x{insn.get('addr', bb):x}",
                    "description": f"Return value of {target}() may not be checked.",
                    "recommendation": f"Check the return value of {target}().",
                })
        return findings

    @staticmethod
    def _strip_prefix(name: str) -> str:
        for prefix in ("sym.imp.", "sym.", "plt.", "reloc."):
            if name.startswith(prefix):
                return name[len(prefix):]
        return name
