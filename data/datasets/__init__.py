"""
Dataset pipeline — collects training data from analysis runs for fine-tuning
GNN and LLM models (Step 9 of M0ST architecture).

Includes:
  - DatasetPipeline: collects samples from analysis runs
  - SourceCompiler: compiles open-source C/C++ projects with/without debug info
  - TrainingDataGenerator: pairs stripped binary functions with source ground truth
"""

import json
import os
import subprocess
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple


class DatasetPipeline:
    """
    Collects and curates datasets from analysis runs for model training.

    Supported dataset types:
      - function_embeddings: CFG embedding vectors paired with function metadata
      - vulnerability_labels: labeled vulnerability data for supervised training
      - symbol_recovery: function name / variable name ground-truth pairs
      - deobfuscation: obfuscated ↔ deobfuscated function pairs
    """

    def __init__(self, datasets_dir: str = "data/datasets"):
        self._datasets_dir = datasets_dir
        self._datasets: Dict[str, List[Dict[str, Any]]] = {
            "function_embeddings": [],
            "vulnerability_labels": [],
            "symbol_recovery": [],
            "deobfuscation": [],
        }

    # ── Embedding dataset ────────────────────────────────────────────

    def add_embedding_sample(
        self,
        binary_sha256: str,
        function_name: str,
        embedding: List[float],
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Record a function embedding sample for training."""
        self._datasets["function_embeddings"].append({
            "binary": binary_sha256,
            "function": function_name,
            "embedding": embedding,
            "metadata": metadata or {},
            "timestamp": time.time(),
        })

    # ── Vulnerability dataset ────────────────────────────────────────

    def add_vulnerability_label(
        self,
        binary_sha256: str,
        function_name: str,
        vuln_type: str,
        severity: str,
        features: Optional[Dict[str, Any]] = None,
    ):
        """Record a labeled vulnerability for supervised training."""
        self._datasets["vulnerability_labels"].append({
            "binary": binary_sha256,
            "function": function_name,
            "vuln_type": vuln_type,
            "severity": severity,
            "features": features or {},
            "timestamp": time.time(),
        })

    # ── Symbol recovery dataset ──────────────────────────────────────

    def add_symbol_ground_truth(
        self,
        binary_sha256: str,
        address: str,
        predicted_name: str,
        ground_truth_name: str,
        correct: bool,
    ):
        """Record a symbol recovery prediction vs ground truth."""
        self._datasets["symbol_recovery"].append({
            "binary": binary_sha256,
            "address": address,
            "predicted": predicted_name,
            "ground_truth": ground_truth_name,
            "correct": correct,
            "timestamp": time.time(),
        })

    # ── Deobfuscation dataset ────────────────────────────────────────

    def add_deobfuscation_pair(
        self,
        binary_sha256: str,
        function_name: str,
        obfuscated_cfg: Dict[str, Any],
        simplified_cfg: Dict[str, Any],
        techniques_found: List[str],
    ):
        """Record an obfuscated ↔ simplified function pair."""
        self._datasets["deobfuscation"].append({
            "binary": binary_sha256,
            "function": function_name,
            "obfuscated": obfuscated_cfg,
            "simplified": simplified_cfg,
            "techniques": techniques_found,
            "timestamp": time.time(),
        })

    # ── Query & export ───────────────────────────────────────────────

    def get_dataset(self, name: str) -> List[Dict[str, Any]]:
        """Get all samples for a dataset type."""
        return self._datasets.get(name, [])

    def dataset_stats(self) -> Dict[str, int]:
        """Return sample counts per dataset type."""
        return {name: len(samples) for name, samples in self._datasets.items()}

    def export_dataset(self, name: str, output_path: Optional[str] = None) -> str:
        """Export a dataset to JSON. Returns the JSON string."""
        samples = self._datasets.get(name, [])
        data = json.dumps(samples, indent=2, default=str)
        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w") as f:
                f.write(data)
        return data

    def clear_dataset(self, name: Optional[str] = None):
        """Clear a specific dataset or all datasets."""
        if name:
            self._datasets[name] = []
        else:
            for key in self._datasets:
                self._datasets[key] = []


class SourceCompiler:
    """
    Compiles open-source C/C++ projects twice: with and without debug symbols.

    Produces a (debug_binary, stripped_binary) pair for each project so that
    TrainingDataGenerator can extract ground-truth function names and types
    from the debug build and pair them with the stripped binary.
    """

    DEFAULT_CFLAGS_DEBUG = ["-g", "-O0"]
    DEFAULT_CFLAGS_STRIPPED = ["-O2", "-s"]

    def __init__(self, output_dir: str = "data/binaries/compiled"):
        self._output_dir = output_dir

    def compile_project(
        self,
        source_dir: str,
        project_name: str,
        compiler: str = "gcc",
        extra_flags: Optional[List[str]] = None,
    ) -> Optional[Dict[str, str]]:
        """
        Compile a C/C++ project with and without debug info.

        Returns dict with 'debug' and 'stripped' binary paths, or None on failure.
        """
        if not os.path.isdir(source_dir):
            return None

        project_out = os.path.join(self._output_dir, project_name)
        os.makedirs(project_out, exist_ok=True)

        debug_bin = os.path.join(project_out, f"{project_name}_debug")
        stripped_bin = os.path.join(project_out, f"{project_name}_stripped")

        sources = self._collect_sources(source_dir)
        if not sources:
            return None

        base_flags = extra_flags or []

        # Debug build
        if not self._run_compile(compiler, sources, debug_bin,
                                 base_flags + self.DEFAULT_CFLAGS_DEBUG):
            return None

        # Stripped build
        if not self._run_compile(compiler, sources, stripped_bin,
                                 base_flags + self.DEFAULT_CFLAGS_STRIPPED):
            return None

        return {"debug": debug_bin, "stripped": stripped_bin}

    def _collect_sources(self, directory: str) -> List[str]:
        """Collect .c and .cpp files from a directory tree."""
        sources = []
        for root, _dirs, files in os.walk(directory):
            for f in files:
                if f.endswith((".c", ".cpp", ".cc")):
                    sources.append(os.path.join(root, f))
        return sources

    @staticmethod
    def _run_compile(compiler: str, sources: List[str], output: str,
                     flags: List[str]) -> bool:
        cmd = [compiler] + flags + sources + ["-o", output]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False


class TrainingDataGenerator:
    """
    Pairs stripped binary functions with source-level ground truth extracted
    from debug builds.

    Workflow:
      1. Use radare2 on the debug binary to extract symbol → address mapping.
      2. Use radare2 on the stripped binary to extract function boundaries.
      3. Match by code bytes / address offsets.
      4. Emit training pairs: (stripped_function_bytes, ground_truth_name, ground_truth_type).
    """

    def __init__(self, pipeline: Optional[DatasetPipeline] = None):
        self._pipeline = pipeline

    def generate_pairs(
        self,
        debug_binary: str,
        stripped_binary: str,
        binary_sha256: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Extract training pairs from a debug/stripped binary pair.

        Returns list of dicts with keys:
          address, ground_truth_name, function_size, binary
        """
        debug_symbols = self._extract_symbols(debug_binary)
        stripped_functions = self._extract_functions(stripped_binary)
        if not debug_symbols or not stripped_functions:
            return []

        pairs = []
        for func in stripped_functions:
            addr = func.get("offset")
            size = func.get("size", 0)
            gt = debug_symbols.get(addr)
            if gt and not gt.startswith("sub_") and not gt.startswith("fcn."):
                pair = {
                    "address": addr,
                    "ground_truth_name": gt,
                    "function_size": size,
                    "binary": binary_sha256,
                }
                pairs.append(pair)
                if self._pipeline:
                    self._pipeline.add_symbol_ground_truth(
                        binary_sha256=binary_sha256,
                        address=hex(addr),
                        predicted_name="",
                        ground_truth_name=gt,
                        correct=False,
                    )
        return pairs

    @staticmethod
    def _extract_symbols(binary_path: str) -> Dict[int, str]:
        """Use r2 to extract symbol names from a debug binary."""
        try:
            import r2pipe
            r2 = r2pipe.open(binary_path, flags=["-2"])
            symbols = r2.cmdj("isj") or []
            r2.quit()
            return {s["vaddr"]: s["name"] for s in symbols
                    if s.get("vaddr") and s.get("name")}
        except Exception:
            return {}

    @staticmethod
    def _extract_functions(binary_path: str) -> List[Dict]:
        """Use r2 to extract function list from a stripped binary."""
        try:
            import r2pipe
            r2 = r2pipe.open(binary_path, flags=["-2"])
            r2.cmd("aaa")
            funcs = r2.cmdj("aflj") or []
            r2.quit()
            return funcs
        except Exception:
            return []
