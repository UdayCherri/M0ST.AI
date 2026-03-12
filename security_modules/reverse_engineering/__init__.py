"""
Reverse Engineering sub-modules — M0ST Security Module.

This module is strictly limited to **program reconstruction** tasks.
It must NOT contain vulnerability detection, exploitability analysis,
malware classification, or unsafe-pattern detection logic.

Allowed capabilities (reconstruction only):
    - binary loading & disassembly
    - CFG recovery
    - call graph generation
    - pseudocode extraction
    - function boundary detection
    - type inference
    - struct recovery
    - symbol recovery (structural)
    - semantic labeling (structural, non-security)
    - deobfuscation (CFG normalization)

Security-focused analysis lives in:
    security_modules/ai_assisted_binary_analysis/
"""
