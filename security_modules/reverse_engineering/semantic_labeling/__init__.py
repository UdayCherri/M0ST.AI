"""
Semantic Labeling — assigns semantic labels to recovered program entities.

Labels include behavioral categories (e.g., "allocator", "string_handler",
"crypto_routine") based on structural and content analysis of functions.
This is a reconstruction task—it describes *what* the code does structurally,
not whether it is malicious.
"""

from typing import Any, Dict, List, Optional


class SemanticLabeler:
    """
    Assigns semantic labels to functions and basic blocks based
    on their structural properties, called APIs, and instruction patterns.
    """

    # Behavioral categories based on API usage
    _API_CATEGORIES = {
        "memory_management": {
            "malloc", "calloc", "realloc", "free", "mmap", "munmap",
            "VirtualAlloc", "VirtualFree", "HeapAlloc", "HeapFree",
        },
        "string_handling": {
            "strlen", "strcpy", "strcat", "strcmp", "strncpy", "strncat",
            "strncmp", "strstr", "strtok", "memcpy", "memset", "memmove",
        },
        "io_operations": {
            "open", "close", "read", "write", "fopen", "fclose",
            "fread", "fwrite", "printf", "scanf", "puts", "gets",
            "CreateFileA", "CreateFileW", "ReadFile", "WriteFile",
        },
        "network": {
            "socket", "connect", "bind", "listen", "accept",
            "send", "recv", "sendto", "recvfrom",
            "WSAStartup", "getaddrinfo",
        },
        "crypto_primitive": {
            "EVP_EncryptInit", "EVP_DecryptInit", "EVP_DigestInit",
            "CryptEncrypt", "CryptDecrypt", "CryptHashData",
            "AES_encrypt", "SHA256_Init", "MD5_Init",
        },
        "threading": {
            "pthread_create", "pthread_join", "pthread_mutex_lock",
            "CreateThread", "WaitForSingleObject", "EnterCriticalSection",
        },
        "error_handling": {
            "perror", "strerror", "GetLastError", "SetLastError",
            "errno",
        },
    }

    def label_function(
        self,
        graph_store,
        func_addr: int,
    ) -> Dict[str, Any]:
        """
        Assign semantic labels to a function based on its content.
        """
        blocks = graph_store.fetch_basic_blocks(func_addr)
        block_insns = {
            bb: graph_store.fetch_block_instructions(bb) for bb in blocks
        }

        calls = self._extract_calls(block_insns)
        categories = self._categorize(calls)

        # Structural classification
        struct_label = self._structural_classification(blocks, block_insns)

        # Instruction pattern labels
        pattern_labels = self._pattern_labels(block_insns)

        all_labels = list(categories) + [struct_label] + pattern_labels
        all_labels = [l for l in all_labels if l]

        return {
            "func_addr": func_addr,
            "labels": all_labels,
            "categories": categories,
            "structural": struct_label,
            "patterns": pattern_labels,
            "call_targets": calls,
        }

    def label_all(self, graph_store) -> Dict[int, Dict[str, Any]]:
        """Label all functions in the graph store."""
        results = {}
        for func in graph_store.fetch_functions():
            addr = func.get("addr")
            if addr is not None:
                results[addr] = self.label_function(graph_store, addr)
        return results

    def _extract_calls(self, block_insns: Dict[int, List[Dict]]) -> List[str]:
        targets = set()
        for insns in block_insns.values():
            for insn in insns:
                mnem = (insn.get("mnemonic") or "").lower()
                if mnem in ("call", "bl", "blr"):
                    ops = insn.get("operands") or []
                    if ops:
                        name = str(ops[0])
                        for prefix in ("sym.imp.", "sym.", "plt.", "reloc."):
                            if name.startswith(prefix):
                                name = name[len(prefix):]
                        targets.add(name)
        return sorted(targets)

    def _categorize(self, calls: List[str]) -> List[str]:
        found = []
        for call in calls:
            base = call.split("@")[0]
            for cat, apis in self._API_CATEGORIES.items():
                if base in apis and cat not in found:
                    found.append(cat)
        return found

    def _structural_classification(
        self,
        blocks: List[int],
        block_insns: Dict[int, List[Dict]],
    ) -> str:
        """Classify function structure."""
        total_insns = sum(len(insns) for insns in block_insns.values())

        if len(blocks) == 1 and total_insns <= 5:
            return "thunk"
        if len(blocks) == 1 and total_insns <= 2:
            return "stub"
        if len(blocks) > 20:
            return "complex"
        if total_insns > 200:
            return "large"
        return "normal"

    def _pattern_labels(self, block_insns: Dict[int, List[Dict]]) -> List[str]:
        """Detect instruction-level patterns."""
        labels = []
        has_loop_back = False
        has_simd = False

        for insns in block_insns.values():
            for insn in insns:
                mnem = (insn.get("mnemonic") or "").lower()
                if mnem.startswith(("vpadd", "vpxor", "vmov", "vpsub", "vpshuf")):
                    has_simd = True
                if mnem.startswith("rep"):
                    labels.append("rep_string_op") if "rep_string_op" not in labels else None

        if has_simd:
            labels.append("simd_operations")

        return labels
