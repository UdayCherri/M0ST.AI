#!/usr/bin/env python3
"""
M0ST unified dataset pipeline.

Flow:
collect -> compile -> strip -> analyze -> graph -> normalize -> merge -> pair -> save
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import hashlib
import io
import json
import os
import pickle
import random
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import torch

    _TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TORCH_AVAILABLE = False

from ai_security_agents.static_agent import StaticAgent
from storage.memory_graph_store import MemoryGraphStore


DATASET_SIZE_TARGETS = {
    "minimum_functions": 50_000,
    "ideal_functions": 500_000,
    "stretch_functions": 1_000_000,
}


MERGE_WEIGHTS = {
    "opensource": 0.60,
    "safe": 0.15,
    "gemini": 0.15,
    "trex": 0.10,
}


MINIMAL_MERGE_WEIGHTS = {
    "opensource": 0.70,
    "safe": 0.15,
    "gemini": 0.15,
}


@dataclass(frozen=True)
class ProjectSpec:
    name: str
    repo_url: str
    pinned_ref: str


DEFAULT_PROJECT_SPECS: Tuple[ProjectSpec, ...] = (
    ProjectSpec("openssl", "https://github.com/openssl/openssl.git", "openssl-3.3.2"),
    ProjectSpec("sqlite", "https://github.com/sqlite/sqlite.git", "version-3.46.0"),
    ProjectSpec("zlib", "https://github.com/madler/zlib.git", "v1.3.1"),
    ProjectSpec("libpng", "https://github.com/glennrp/libpng.git", "v1.6.43"),
    ProjectSpec("curl", "https://github.com/curl/curl.git", "curl-8_8_0"),
    ProjectSpec("coreutils", "https://github.com/coreutils/coreutils.git", "v9.5"),
    ProjectSpec("busybox", "https://github.com/mirror/busybox.git", "1_36_1"),
)


DEFAULT_COMPILERS = ("gcc", "clang")
DEFAULT_OPT_LEVELS = ("O0", "O2", "O3")
DEFAULT_COMPILE_VARIANTS: Tuple[Tuple[str, str], ...] = (
    ("gcc", "O0"),
    ("gcc", "O2"),
    ("gcc", "O3"),
    ("clang", "O2"),
)


_OPCODE_BUCKETS: Dict[str, int] = {
    "mov": 0,
    "lea": 0,
    "movzx": 0,
    "movsx": 0,
    "cmov": 0,
    "push": 1,
    "pop": 1,
    "add": 2,
    "sub": 2,
    "inc": 2,
    "dec": 2,
    "neg": 2,
    "adc": 2,
    "sbb": 2,
    "mul": 3,
    "imul": 3,
    "div": 3,
    "idiv": 3,
    "and": 4,
    "or": 4,
    "xor": 4,
    "not": 4,
    "shl": 4,
    "shr": 4,
    "sar": 4,
    "rol": 4,
    "ror": 4,
    "cmp": 5,
    "test": 5,
    "jmp": 6,
    "je": 6,
    "jz": 6,
    "jne": 6,
    "jnz": 6,
    "jg": 6,
    "jge": 6,
    "jl": 6,
    "jle": 6,
    "ja": 6,
    "jb": 6,
    "call": 7,
    "bl": 7,
    "blr": 7,
    "ret": 8,
    "retn": 8,
    "retq": 8,
    "leave": 8,
    "nop": 9,
    "syscall": 10,
    "int": 10,
    "svc": 10,
}


_NUM_OPCODE_BINS = 12


SYNTHETIC_TEMPLATES: Dict[str, List[Tuple[str, str]]] = {
    "sorting_algorithms": [
        (
            "bubble_sort",
            """
#include <stdio.h>

static void bubble_sort(int *arr, int n) {
    for (int i = 0; i < n - 1; i++) {
        for (int j = 0; j < n - i - 1; j++) {
            if (arr[j] > arr[j + 1]) {
                int tmp = arr[j];
                arr[j] = arr[j + 1];
                arr[j + 1] = tmp;
            }
        }
    }
}

int main(void) {
    int arr[8] = {9, 2, 7, 1, 3, 8, 4, 6};
    bubble_sort(arr, 8);
    printf("%d\\n", arr[0]);
    return 0;
}
""".strip(),
        )
    ],
    "hash_functions": [
        (
            "djb2_hash",
            """
#include <stdint.h>
#include <stdio.h>

static uint32_t djb2(const char *s) {
    uint32_t h = 5381U;
    while (*s) {
        h = ((h << 5) + h) + (uint8_t)*s;
        s++;
    }
    return h;
}

int main(void) {
    printf("%u\\n", djb2("m0st_dataset"));
    return 0;
}
""".strip(),
        )
    ],
    "string_manipulation": [
        (
            "reverse_string",
            """
#include <stdio.h>
#include <string.h>

static void reverse(char *s) {
    int i = 0;
    int j = (int)strlen(s) - 1;
    while (i < j) {
        char t = s[i];
        s[i] = s[j];
        s[j] = t;
        i++;
        j--;
    }
}

int main(void) {
    char data[32] = "reverse_me";
    reverse(data);
    puts(data);
    return 0;
}
""".strip(),
        )
    ],
}


class DatasetBuilder:
    """Orchestrates collection, build, analysis, normalization, and fusion."""

    def __init__(self, root_dir: str = "data/datasets", seed: int = 1337):
        self.root = Path(root_dir)
        self.source_dir = self.root / "source_code"
        self.compiled_dir = self.root / "compiled"
        self.stripped_dir = self.root / "stripped"
        self.synthetic_dir = self.root / "synthetic"

        self.external_dir = self.root / "external"
        self.external_safe_dir = self.external_dir / "safe"
        self.external_trex_dir = self.external_dir / "trex"
        self.external_gemini_dir = self.external_dir / "gemini"

        self.raw_graphs_dir = self.root / "raw_graphs"
        self.graphs_dir = self.root / "graphs"
        self.cache_dir = self.root / "cache"
        self.pairs_dir = self.root / "pairs"
        self.metadata_dir = self.root / "metadata"
        self.scripts_dir = self.root / "scripts"
        self.processed_ids_path = self.metadata_dir / "processed_ids.json"

        self._project_specs = {p.name: p for p in DEFAULT_PROJECT_SPECS}
        self._function_counter = 0
        self._external_counter = 0
        self.safe_max_functions: Optional[int] = None
        self.gemini_max_graphs: Optional[int] = None
        self.trex_max_binaries: Optional[int] = None
        self.verbose: bool = False
        self.progress_interval: int = 250
        self.max_total_graphs: Optional[int] = None
        self.sampling_mode: str = "random"
        self.pair_limit: int = 50_000
        self.normalize_workers: int = 1
        self.minimal_mode: bool = False
        random.seed(seed)

    def _log(self, message: str) -> None:
        if self.verbose:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] {message}")

    # ---------------------------------------------------------------
    # Helpers and layout
    # ---------------------------------------------------------------

    def ensure_layout(self) -> None:
        for path in (
            self.root,
            self.source_dir,
            self.compiled_dir,
            self.stripped_dir,
            self.synthetic_dir,
            self.external_dir,
            self.external_safe_dir,
            self.external_trex_dir,
            self.external_gemini_dir,
            self.raw_graphs_dir,
            self.graphs_dir,
            self.cache_dir,
            self.pairs_dir,
            self.metadata_dir,
            self.scripts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def _load_processed_ids(self) -> set[str]:
        payload = self._read_json(self.processed_ids_path, default={"processed_ids": []})
        if not isinstance(payload, dict):
            return set()
        ids = payload.get("processed_ids", [])
        if not isinstance(ids, list):
            return set()
        return {str(x) for x in ids}

    def _save_processed_ids(self, processed_ids: set[str]) -> None:
        self._write_json(
            self.processed_ids_path,
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "processed_ids": sorted(processed_ids),
            },
        )

    def _run(
        self,
        command: Sequence[str],
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        merged_env.setdefault("GIT_TERMINAL_PROMPT", "0")

        result = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            message = stderr if stderr else stdout
            raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}\\n{message}")
        return result

    def _resolve_radare2_path(self) -> Optional[str]:
        for exe in ("r2", "radare2"):
            path = shutil.which(exe)
            if path:
                return path

        # Fallback to config.yml: tools.r2_path
        config_path = Path("config.yml")
        if config_path.exists():
            try:
                text = config_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                text = ""
            match = re.search(r"^\s*r2_path\s*:\s*\"?([^\"\n]+)\"?\s*$", text, flags=re.MULTILINE)
            if match:
                candidate = match.group(1).strip()
                if candidate and Path(candidate).exists():
                    return candidate
        return None

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, default=str)

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _is_probable_binary(path: Path) -> bool:
        if not path.is_file():
            return False

        blocked_ext = {
            ".c",
            ".cc",
            ".cpp",
            ".h",
            ".hpp",
            ".o",
            ".obj",
            ".a",
            ".la",
            ".lib",
            ".pdb",
            ".txt",
            ".md",
            ".json",
            ".jsonl",
            ".csv",
            ".yml",
            ".yaml",
            ".py",
        }
        if path.suffix.lower() in blocked_ext:
            return False

        known_binary_ext = {".so", ".dll", ".exe", ".bin", ".dylib"}
        if path.suffix.lower() in known_binary_ext:
            return True

        try:
            with path.open("rb") as handle:
                magic = handle.read(4)
        except OSError:
            return False

        if magic.startswith(b"\x7fELF"):
            return True
        if magic.startswith(b"MZ"):
            return True
        if magic in {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe"}:
            return True
        return os.access(path, os.X_OK)

    @staticmethod
    def _canonical_function_name(name: Optional[str]) -> str:
        if not name:
            return "unknown"
        cleaned = name.strip().lower()
        if cleaned.startswith("sym."):
            cleaned = cleaned[4:]
        return cleaned

    # ---------------------------------------------------------------
    # Step 2: open-source collection
    # ---------------------------------------------------------------

    def collect_open_source_code(
        self,
        projects: Optional[Sequence[str]] = None,
        update_existing: bool = False,
    ) -> Dict[str, Dict[str, str]]:
        self.ensure_layout()
        selected = list(projects) if projects else list(self._project_specs.keys())
        manifest: Dict[str, Dict[str, str]] = {}

        for name in selected:
            if name not in self._project_specs:
                raise ValueError(f"Unknown project: {name}")

            spec = self._project_specs[name]
            repo_dir = self.source_dir / name

            if not repo_dir.exists():
                self._run(["git", "clone", spec.repo_url, str(repo_dir)])
            elif update_existing:
                self._run(["git", "fetch", "--all", "--tags"], cwd=repo_dir, check=False)

            self._run(["git", "fetch", "--all", "--tags"], cwd=repo_dir, check=False)
            self._run(["git", "checkout", "--detach", spec.pinned_ref], cwd=repo_dir)
            commit = self._run(["git", "rev-parse", "HEAD"], cwd=repo_dir).stdout.strip()

            manifest[name] = {
                "repo_url": spec.repo_url,
                "pinned_ref": spec.pinned_ref,
                "resolved_commit": commit,
                "path": str(repo_dir),
            }

        self._write_json(
            self.metadata_dir / "source_manifest.json",
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "projects": manifest,
            },
        )
        return manifest

    # ---------------------------------------------------------------
    # Step 3: compile variants
    # ---------------------------------------------------------------

    def compile_open_source_matrix(
        self,
        projects: Optional[Sequence[str]] = None,
        compile_variants: Sequence[Tuple[str, str]] = DEFAULT_COMPILE_VARIANTS,
        jobs: int = 4,
    ) -> List[Dict[str, Any]]:
        self.ensure_layout()
        selected = list(projects) if projects else list(self._project_specs.keys())
        results: List[Dict[str, Any]] = []

        for project_name in selected:
            project_root = self.source_dir / project_name
            if not project_root.exists():
                results.append(
                    {
                        "project": project_name,
                        "status": "missing_source",
                        "message": "source directory does not exist",
                    }
                )
                continue

            for compiler, opt in compile_variants:
                variant_name = f"{project_name}_{opt}_{compiler}"
                variant_dir = self.compiled_dir / variant_name
                build_dir = variant_dir / "_build"
                variant_dir.mkdir(parents=True, exist_ok=True)
                build_dir.mkdir(parents=True, exist_ok=True)

                env = {
                    "CC": compiler,
                    "CXX": "clang++" if compiler == "clang" else "g++",
                    "CFLAGS": f"-{opt} -g -fno-omit-frame-pointer",
                    "CXXFLAGS": f"-{opt} -g -fno-omit-frame-pointer",
                }

                try:
                    self._build_project(project_root, build_dir, env, jobs)
                    copied = self._collect_binaries_from_build(
                        project_name=project_name,
                        compiler=compiler,
                        opt_level=opt,
                        search_roots=[build_dir, project_root],
                        output_dir=variant_dir,
                    )
                    results.append(
                        {
                            "project": project_name,
                            "compiler": compiler,
                            "optimization": opt,
                            "variant_dir": str(variant_dir),
                            "status": "ok" if copied else "no_binaries",
                            "binary_count": copied,
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    results.append(
                        {
                            "project": project_name,
                            "compiler": compiler,
                            "optimization": opt,
                            "variant_dir": str(variant_dir),
                            "status": "build_failed",
                            "error": str(exc),
                        }
                    )

        self._write_json(
            self.metadata_dir / "compile_manifest.json",
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "variants": [{"compiler": c, "optimization": o} for c, o in compile_variants],
                "results": results,
            },
        )
        return results

    def _build_project(self, project_root: Path, build_dir: Path, env: Dict[str, str], jobs: int) -> None:
        cmake_file = project_root / "CMakeLists.txt"
        configure_script = project_root / "configure"
        makefile = project_root / "Makefile"

        if cmake_file.exists():
            self._run(
                [
                    "cmake",
                    "-S",
                    str(project_root),
                    "-B",
                    str(build_dir),
                    f"-DCMAKE_C_COMPILER={env['CC']}",
                    f"-DCMAKE_CXX_COMPILER={env['CXX']}",
                    f"-DCMAKE_C_FLAGS={env['CFLAGS']}",
                    f"-DCMAKE_CXX_FLAGS={env['CXXFLAGS']}",
                    "-DCMAKE_BUILD_TYPE=Release",
                ],
                env=env,
            )
            self._run(["cmake", "--build", str(build_dir), "--parallel", str(jobs)], env=env)
            return

        if configure_script.exists():
            self._run([str(configure_script), "--disable-shared", "--enable-static"], cwd=build_dir, env=env)
            self._run(["make", "-j", str(jobs)], cwd=build_dir, env=env)
            return

        if makefile.exists():
            self._run(["make", "clean"], cwd=project_root, env=env, check=False)
            self._run(["make", "-j", str(jobs)], cwd=project_root, env=env)
            return

        raise RuntimeError("Unsupported build system (no CMakeLists.txt/configure/Makefile)")

    def _collect_binaries_from_build(
        self,
        project_name: str,
        compiler: str,
        opt_level: str,
        search_roots: Sequence[Path],
        output_dir: Path,
    ) -> int:
        artifacts = output_dir / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)

        seen: set[str] = set()
        copied = 0
        for root in search_roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not self._is_probable_binary(path):
                    continue

                canonical = str(path.resolve())
                if canonical in seen:
                    continue
                seen.add(canonical)

                target = artifacts / f"{project_name}_{opt_level}_{compiler}_{path.name}"
                if target.exists():
                    target = artifacts / f"{target.stem}_{copied:04d}{target.suffix}"
                shutil.copy2(path, target)
                copied += 1
        return copied

    # ---------------------------------------------------------------
    # Step 3b: synthetic generation and compilation
    # ---------------------------------------------------------------

    def generate_synthetic_programs(self, programs_per_category: int = 8) -> List[str]:
        self.ensure_layout()
        generated: List[str] = []

        for category, templates in SYNTHETIC_TEMPLATES.items():
            category_dir = self.synthetic_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)

            for idx in range(programs_per_category):
                template_name, template_body = templates[idx % len(templates)]
                source_name = f"{template_name}_{idx:03d}.c"
                source_path = category_dir / source_name
                source_path.write_text(template_body + f"\\n/* synthetic_variant={idx} */\\n", encoding="utf-8")
                generated.append(str(source_path))

        self._write_json(
            self.metadata_dir / "synthetic_manifest.json",
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "program_count": len(generated),
                "files": generated,
            },
        )
        return generated

    def compile_synthetic_matrix(
        self,
        compile_variants: Sequence[Tuple[str, str]] = DEFAULT_COMPILE_VARIANTS,
    ) -> List[Dict[str, Any]]:
        self.ensure_layout()
        results: List[Dict[str, Any]] = []

        for source_path in sorted(self.synthetic_dir.rglob("*.c")):
            source_id = source_path.stem
            for compiler, opt in compile_variants:
                variant_name = f"synthetic_{source_id}_{opt}_{compiler}"
                variant_dir = self.compiled_dir / variant_name
                variant_dir.mkdir(parents=True, exist_ok=True)

                out_bin = variant_dir / f"{source_id}_{opt}_{compiler}"
                proc = self._run(
                    [
                        compiler,
                        f"-{opt}",
                        "-g",
                        "-fno-omit-frame-pointer",
                        str(source_path),
                        "-o",
                        str(out_bin),
                    ],
                    check=False,
                )

                resolved_output = self._resolve_compiler_output_path(out_bin)
                status = "ok" if proc.returncode == 0 and resolved_output else "compile_failed"

                if status == "ok":
                    artifacts_dir = variant_dir / "artifacts"
                    artifacts_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(resolved_output, artifacts_dir / resolved_output.name)

                results.append(
                    {
                        "source": str(source_path),
                        "compiler": compiler,
                        "optimization": opt,
                        "output": str(resolved_output or out_bin),
                        "status": status,
                        "stderr": (proc.stderr or "").strip()[-1000:],
                    }
                )

        self._write_json(
            self.metadata_dir / "synthetic_compile_manifest.json",
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "variants": [{"compiler": c, "optimization": o} for c, o in compile_variants],
                "results": results,
            },
        )
        return results

    @staticmethod
    def _resolve_compiler_output_path(requested_output: Path) -> Optional[Path]:
        if requested_output.exists():
            return requested_output
        exe_candidate = requested_output.with_suffix(requested_output.suffix + ".exe")
        if exe_candidate.exists():
            return exe_candidate
        return None

    # ---------------------------------------------------------------
    # Step 4: strip binaries
    # ---------------------------------------------------------------

    def strip_compiled_binaries(self) -> List[Dict[str, Any]]:
        self.ensure_layout()
        strip_tool = self._resolve_strip_tool()
        results: List[Dict[str, Any]] = []

        for variant_dir in sorted(self.compiled_dir.glob("*")):
            if not variant_dir.is_dir():
                continue

            artifact_dir = variant_dir / "artifacts"
            if not artifact_dir.exists():
                continue

            target_variant = self.stripped_dir / f"{variant_dir.name}_stripped"
            target_variant.mkdir(parents=True, exist_ok=True)

            for binary_path in artifact_dir.glob("*"):
                if not self._is_probable_binary(binary_path):
                    continue

                out_path = target_variant / binary_path.name
                shutil.copy2(binary_path, out_path)
                if strip_tool:
                    proc = self._run([strip_tool, str(out_path)], check=False)
                    status = "ok" if proc.returncode == 0 else "strip_failed"
                else:
                    status = "copied_without_strip"

                results.append(
                    {
                        "input": str(binary_path),
                        "output": str(out_path),
                        "strip_tool": strip_tool,
                        "status": status,
                    }
                )

        self._write_json(
            self.metadata_dir / "strip_manifest.json",
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "results": results,
            },
        )
        return results

    @staticmethod
    def _resolve_strip_tool() -> Optional[str]:
        for tool in ("strip", "llvm-strip"):
            if shutil.which(tool):
                return tool
        return None

    # ---------------------------------------------------------------
    # Step 4/5: graph extraction (internal + external)
    # ---------------------------------------------------------------

    def _clear_existing_graph_outputs(self) -> None:
        self._function_counter = 0
        paths = list(self.graphs_dir.glob("*.pt"))
        total = len(paths)
        if total:
            self._log(f"Clearing normalized graphs: total={total}")
        for idx, graph_path in enumerate(paths, start=1):
            graph_path.unlink()
            if idx % max(1, self.progress_interval) == 0:
                self._log(f"Clear normalized progress: deleted={idx}/{total}")
        if self.processed_ids_path.exists():
            self.processed_ids_path.unlink()

    def _clear_existing_raw_graphs(self) -> None:
        self._function_counter = 0
        self._external_counter = 0
        paths = list(self.raw_graphs_dir.glob("*.pt"))
        total = len(paths)
        if total:
            self._log(f"Clearing raw graphs: total={total}")
        for idx, graph_path in enumerate(paths, start=1):
            graph_path.unlink()
            if idx % max(1, self.progress_interval) == 0:
                self._log(f"Clear raw progress: deleted={idx}/{total}")

    def _gather_binary_files(self, root: Path) -> List[Path]:
        if not root.exists():
            return []
        output: List[Path] = []
        for path in root.rglob("*"):
            if self._is_probable_binary(path):
                output.append(path)
        return output

    def build_raw_graphs_from_binaries(
        self,
        include_compiled: bool = False,
        include_stripped: bool = True,
        max_binaries: Optional[int] = None,
    ) -> Dict[str, Any]:
        self.ensure_layout()
        if not _TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required to serialize graph files")

        self._clear_existing_raw_graphs()

        binary_paths: List[Path] = []
        if include_stripped:
            binary_paths.extend(self._gather_binary_files(self.stripped_dir))
        if include_compiled:
            binary_paths.extend(self._gather_binary_files(self.compiled_dir))

        binary_paths = sorted({p.resolve() for p in binary_paths})
        if max_binaries is not None and len(binary_paths) > max_binaries:
            rng = random.Random(1337)
            binary_paths = sorted(rng.sample(binary_paths, max_binaries))
            self._log(f"Open-source binary cap active: selected={len(binary_paths)}")
        labels: List[Dict[str, Any]] = []
        analyzed_binaries = 0

        for binary_path in binary_paths:
            try:
                labels.extend(self._analyze_binary_and_serialize_raw(binary_path))
                analyzed_binaries += 1
            except Exception as exc:  # pragma: no cover
                labels.append(
                    {
                        "function_id": None,
                        "function_name": None,
                        "source_dataset": "opensource",
                        "project_name": "unknown",
                        "compiler": "unknown",
                        "optimization_level": "unknown",
                        "binary_name": binary_path.name,
                        "binary_path": str(binary_path),
                        "graph_path": None,
                        "error": str(exc),
                    }
                )

        self._write_json(self.metadata_dir / "raw_function_labels.json", labels)
        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "analyzed_binaries": analyzed_binaries,
            "raw_graph_count": len([x for x in labels if x.get("graph_path")]),
        }
        self._write_json(self.metadata_dir / "raw_graph_summary.json", summary)
        return summary

    def _analyze_binary_and_serialize_raw(self, binary_path: Path) -> List[Dict[str, Any]]:
        graph_store = MemoryGraphStore()
        agent = StaticAgent(graph_store)
        agent.run(str(binary_path), verbose=False)

        variant_meta = self._extract_variant_metadata(binary_path)
        entries: List[Dict[str, Any]] = []

        for func in graph_store.fetch_functions():
            func_addr = func.get("addr")
            if func_addr is None:
                continue

            blocks = graph_store.fetch_basic_blocks(func_addr)
            edges = graph_store.fetch_flow_edges(func_addr)
            if not blocks:
                continue

            self._function_counter += 1
            function_id = f"func_{self._function_counter:07d}"
            graph_path = self.raw_graphs_dir / f"{function_id}.pt"

            node_features = self._build_node_features(graph_store, blocks, edges)
            edge_index = self._build_edge_index(blocks, edges)

            payload = {
                "function_id": function_id,
                "function_name": func.get("name", f"sub_{int(func_addr):x}"),
                "source": "opensource",
                "source_dataset": "opensource",
                "project_name": variant_meta["source_project"],
                "binary_name": binary_path.name,
                "binary_path": str(binary_path),
                "compiler": variant_meta["compiler"],
                "optimization_level": variant_meta["optimization_level"],
                "node_features": node_features,
                "edge_index": edge_index,
                "num_nodes": len(node_features),
            }
            torch.save(payload, graph_path)

            entries.append(
                {
                    "function_id": function_id,
                    "function_name": payload["function_name"],
                    "source_dataset": "opensource",
                    "project_name": payload["project_name"],
                    "compiler": payload["compiler"],
                    "optimization_level": payload["optimization_level"],
                    "binary_name": payload["binary_name"],
                    "binary_path": str(binary_path),
                    "graph_path": str(graph_path),
                }
            )

        return entries

    def _extract_variant_metadata(self, binary_path: Path) -> Dict[str, str]:
        parent_name = binary_path.parent.name
        grandparent_name = binary_path.parent.parent.name if binary_path.parent.parent else ""
        variant = grandparent_name if parent_name == "artifacts" else parent_name

        match = re.match(r"^(?P<project>.+?)_(?P<opt>O[0-3])_(?P<compiler>gcc|clang)(?:_stripped)?$", variant)
        if not match:
            return {
                "source_project": "unknown",
                "compiler": "unknown",
                "optimization_level": "unknown",
            }

        return {
            "source_project": match.group("project"),
            "compiler": match.group("compiler"),
            "optimization_level": match.group("opt"),
        }

    def _build_edge_index(self, blocks: List[int], edges: List[Tuple[int, int]]) -> List[List[int]]:
        block_to_idx = {bb: i for i, bb in enumerate(blocks)}
        src_list: List[int] = []
        dst_list: List[int] = []
        for src, dst in edges:
            if src in block_to_idx and dst in block_to_idx:
                src_list.append(block_to_idx[src])
                dst_list.append(block_to_idx[dst])
        return [src_list, dst_list]

    def _build_node_features(
        self,
        graph_store: MemoryGraphStore,
        blocks: List[int],
        edges: List[Tuple[int, int]],
    ) -> List[List[float]]:
        loop_depths = self._estimate_loop_depths(blocks, edges)
        in_degree: Dict[int, int] = {bb: 0 for bb in blocks}
        out_degree: Dict[int, int] = {bb: 0 for bb in blocks}

        for src, dst in edges:
            if src in out_degree:
                out_degree[src] += 1
            if dst in in_degree:
                in_degree[dst] += 1

        node_features: List[List[float]] = []
        for bb in blocks:
            insns = graph_store.fetch_block_instructions(bb)
            hist = [0.0] * _NUM_OPCODE_BINS
            call_count = 0
            branch_count = 0

            for insn in insns:
                mnem = (insn.get("mnemonic") or "").lower()
                bucket = _OPCODE_BUCKETS.get(mnem, _NUM_OPCODE_BINS - 1)
                hist[bucket] += 1.0
                if mnem.startswith("call") or mnem in {"bl", "blr"}:
                    call_count += 1
                if (mnem.startswith("j") and mnem not in {"jmp"}) or mnem in {"jmp", "b", "beq", "bne"}:
                    branch_count += 1

            total_hist = sum(hist)
            if total_hist > 0:
                hist = [v / total_hist for v in hist]

            node_features.append(
                hist
                + [
                    float(len(insns)),
                    float(in_degree.get(bb, 0)),
                    float(out_degree.get(bb, 0)),
                    float(call_count),
                    float(branch_count),
                    float(loop_depths.get(bb, 0)),
                ]
            )
        return node_features

    @staticmethod
    def _estimate_loop_depths(blocks: List[int], edges: List[Tuple[int, int]]) -> Dict[int, int]:
        adjacency: Dict[int, List[int]] = {bb: [] for bb in blocks}
        reverse_adjacency: Dict[int, List[int]] = {bb: [] for bb in blocks}
        self_loops: Dict[int, bool] = {bb: False for bb in blocks}

        for src, dst in edges:
            if src not in adjacency or dst not in adjacency:
                continue
            adjacency[src].append(dst)
            reverse_adjacency[dst].append(src)
            if src == dst:
                self_loops[src] = True

        visited: set[int] = set()
        order: List[int] = []

        def dfs(node: int) -> None:
            visited.add(node)
            for nxt in adjacency[node]:
                if nxt not in visited:
                    dfs(nxt)
            order.append(node)

        for bb in blocks:
            if bb not in visited:
                dfs(bb)

        visited.clear()
        components: List[List[int]] = []

        def reverse_dfs(node: int, acc: List[int]) -> None:
            visited.add(node)
            acc.append(node)
            for prev in reverse_adjacency[node]:
                if prev not in visited:
                    reverse_dfs(prev, acc)

        for bb in reversed(order):
            if bb in visited:
                continue
            component: List[int] = []
            reverse_dfs(bb, component)
            components.append(component)

        depth: Dict[int, int] = {bb: 0 for bb in blocks}
        for comp in components:
            if len(comp) > 1:
                for bb in comp:
                    depth[bb] += 1
            elif comp and self_loops.get(comp[0], False):
                depth[comp[0]] += 1
        return depth

    def integrate_external_datasets(self, sources: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        self.ensure_layout()
        if not _TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required to serialize graph files")

        self._log("Starting external dataset integration")

        summaries: Dict[str, Dict[str, Any]] = {}
        dataset_roots = {
            "safe": self.external_safe_dir,
            "trex": self.external_trex_dir,
            "gemini": self.external_gemini_dir,
        }

        selected = [s.strip().lower() for s in (sources or dataset_roots.keys()) if s and s.strip()]
        for dataset_name in selected:
            if dataset_name not in dataset_roots:
                summaries[dataset_name] = {
                    "status": "unknown_dataset",
                    "converted": 0,
                    "skipped": 0,
                    "files_seen": 0,
                }
                continue

            root = dataset_roots[dataset_name]
            converted = 0
            skipped = 0
            files_seen = 0
            self._log(f"Scanning external dataset: {dataset_name} ({root})")

            if not root.exists():
                summaries[dataset_name] = {
                    "status": "missing_directory",
                    "converted": 0,
                    "skipped": 0,
                    "files_seen": 0,
                }
                continue

            if dataset_name == "safe":
                for file_path in sorted(root.rglob("*.db")):
                    files_seen += 1
                    self._log(f"SAFE ingest: {file_path.name}")
                    try:
                        c, s = self._convert_safe_database(file_path)
                        converted += c
                        skipped += s
                    except Exception:
                        skipped += 1
                    self._log(f"SAFE progress: converted={converted} skipped={skipped} files={files_seen}")
                summaries[dataset_name] = {
                    "status": "ok",
                    "converted": converted,
                    "skipped": skipped,
                    "files_seen": files_seen,
                    "directory": str(root),
                }
                continue

            if dataset_name == "gemini":
                for file_path in sorted(root.rglob("*.cfg")):
                    files_seen += 1
                    self._log(f"Gemini ingest: {file_path.name}")
                    try:
                        c, s = self._convert_gemini_cfg(file_path)
                        converted += c
                        skipped += s
                    except Exception:
                        skipped += 1
                    self._log(f"Gemini progress: converted={converted} skipped={skipped} files={files_seen}")
                summaries[dataset_name] = {
                    "status": "ok",
                    "converted": converted,
                    "skipped": skipped,
                    "files_seen": files_seen,
                    "directory": str(root),
                }
                continue

            # Trex is distributed mostly as raw binaries.
            r2_path = self._resolve_radare2_path()
            if not r2_path:
                self._log("Trex ingestion skipped: radare2 (r2) not found in PATH or config.yml tools.r2_path")
                summaries[dataset_name] = {
                    "status": "missing_radare2",
                    "converted": 0,
                    "skipped": 0,
                    "files_seen": 0,
                    "directory": str(root),
                }
                continue

            trex_seen = 0
            for file_path in sorted(root.rglob("*")):
                if not file_path.is_file() or not self._is_probable_binary(file_path):
                    continue
                if self.trex_max_binaries is not None and trex_seen >= self.trex_max_binaries:
                    break
                files_seen += 1
                trex_seen += 1
                if trex_seen == 1 or trex_seen % max(1, self.progress_interval // 5) == 0:
                    self._log(
                        f"Trex binary progress: seen={trex_seen} converted={converted} skipped={skipped}"
                    )
                try:
                    c, s = self._convert_trex_binary(file_path)
                    converted += c
                    skipped += s
                except Exception:
                    skipped += 1

            summaries[dataset_name] = {
                "status": "ok",
                "converted": converted,
                "skipped": skipped,
                "files_seen": files_seen,
                "directory": str(root),
            }

        self._write_json(
            self.metadata_dir / "external_ingest_summary.json",
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "datasets": summaries,
            },
        )
        self._log("External dataset integration complete")
        return summaries

    def _save_external_payload(self, payload: Dict[str, Any], source: str) -> bool:
        normalized = self._coerce_to_graph_payload(payload, source=source)
        if not normalized:
            return False

        self._external_counter += 1
        normalized["function_id"] = normalized.get("function_id") or f"ext_{source}_{self._external_counter:08d}"
        out_path = self.raw_graphs_dir / f"{normalized['function_id']}.pt"
        torch.save(normalized, out_path)
        return True

    def _convert_safe_database(self, db_path: Path) -> Tuple[int, int]:
        converted = 0
        skipped = 0
        self._log(f"Reading SAFE database: {db_path}")

        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()

            try:
                rows_iter = cur.execute(
                    "SELECT id, project, compiler, optimization, file_name, function_name, num_instructions FROM functions"
                )
            except sqlite3.Error:
                return 0, 1

            for row in rows_iter:
                if self.safe_max_functions is not None and converted >= self.safe_max_functions:
                    break
                try:
                    func_id = int(row[0])
                    project = str(row[1] or "safe")
                    compiler = str(row[2] or "unknown")
                    optimization = str(row[3] or "unknown")
                    file_name = str(row[4] or db_path.name)
                    function_name = str(row[5] or f"fn_{func_id}")
                    instruction_count = int(row[6] or 0)

                    insn_ids: List[int] = []
                    try:
                        filtered_row = cur.execute(
                            "SELECT instructions_list FROM filtered_functions WHERE id = ?",
                            (func_id,),
                        ).fetchone()
                    except sqlite3.Error:
                        filtered_row = None

                    if filtered_row and filtered_row[0]:
                        raw_list = filtered_row[0]
                        try:
                            parsed = json.loads(raw_list)
                        except Exception:
                            parsed = ast.literal_eval(raw_list)
                        if isinstance(parsed, list):
                            insn_ids = [int(x) for x in parsed]

                    hist = [0.0] * _NUM_OPCODE_BINS
                    if insn_ids:
                        for insn_id in insn_ids:
                            hist[int(insn_id) % _NUM_OPCODE_BINS] += 1.0
                    total = sum(hist)
                    if total > 0:
                        hist = [x / total for x in hist]

                    node_features = [
                        hist + [
                            float(instruction_count),
                            0.0,
                            0.0,
                            0.0,
                            0.0,
                            0.0,
                        ]
                    ]

                    payload = {
                        "function_id": f"safe_{db_path.stem}_{func_id}",
                        "function_name": function_name,
                        "source": "safe",
                        "source_dataset": "safe",
                        "project_name": project,
                        "binary_name": file_name,
                        "binary_path": str(db_path),
                        "compiler": compiler,
                        "optimization_level": optimization,
                        "node_features": node_features,
                        "edge_index": [[], []],
                        "num_nodes": 1,
                    }

                    if self._save_external_payload(payload, source="safe"):
                        converted += 1
                        if converted % max(1, self.progress_interval) == 0:
                            self._log(f"SAFE function progress: converted={converted} from {db_path.name}")
                    else:
                        skipped += 1
                except Exception:
                    skipped += 1
        finally:
            conn.close()

        return converted, skipped

    def _convert_gemini_cfg(self, cfg_path: Path) -> Tuple[int, int]:
        converted = 0
        skipped = 0
        self._log(f"Reading Gemini CFG: {cfg_path.name}")

        class _GeminiDummy:
            pass

        class _GeminiUnpickler(pickle.Unpickler):
            def find_class(self, module: str, name: str) -> Any:
                mapped_module = module
                if mapped_module == "copy_reg":
                    mapped_module = "copyreg"
                if mapped_module == "__builtin__":
                    mapped_module = "builtins"

                if mapped_module.startswith("networkx") or mapped_module in {"copyreg", "builtins"}:
                    return super().find_class(mapped_module, name)
                return _GeminiDummy

        raw = cfg_path.read_bytes().replace(b"\r", b"")
        root = _GeminiUnpickler(io.BytesIO(raw)).load()
        raw_graphs = getattr(root, "raw_graph_list", None)
        if not isinstance(raw_graphs, list):
            return 0, 1

        name_match = re.match(
            r"^(?P<project>.+)_(?P<arch>[^_]+)_(?P<compiler>gcc|clang)_(?P<opt>O[0-3])_(?P<binary>.+)\.cfg$",
            cfg_path.name,
        )
        default_project = name_match.group("project") if name_match else "gemini"
        default_compiler = name_match.group("compiler") if name_match else "unknown"
        default_opt = name_match.group("opt") if name_match else "unknown"
        default_binary = (name_match.group("binary") if name_match else cfg_path.stem) + ".bin"

        for raw_graph in raw_graphs:
            if self.gemini_max_graphs is not None and converted >= self.gemini_max_graphs:
                break
            try:
                old_g = getattr(raw_graph, "old_g", None)
                if old_g is None:
                    old_g = getattr(raw_graph, "g", None)
                if old_g is None:
                    skipped += 1
                    continue

                nodes = list(old_g.nodes(data=True))
                node_id_to_idx = {node_id: idx for idx, (node_id, _) in enumerate(nodes)}

                src: List[int] = []
                dst: List[int] = []
                for edge_src, edge_dst in old_g.edges():
                    if edge_src in node_id_to_idx and edge_dst in node_id_to_idx:
                        src.append(node_id_to_idx[edge_src])
                        dst.append(node_id_to_idx[edge_dst])

                node_features: List[List[float]] = []
                for node_id, attrs in nodes:
                    attrs = attrs or {}
                    indeg = float(old_g.in_degree(node_id))
                    outdeg = float(old_g.out_degree(node_id))
                    instruction_count = float(attrs.get("numIns", 0))
                    call_count = float(attrs.get("numCalls", 0))
                    branch_count = float(attrs.get("numAs", 0) + attrs.get("numTIs", 0))
                    loop_depth = float(attrs.get("numLIs", 0))

                    hist = [0.0] * _NUM_OPCODE_BINS
                    hist[-1] = 1.0
                    node_features.append(
                        hist
                        + [
                            instruction_count,
                            indeg,
                            outdeg,
                            call_count,
                            branch_count,
                            loop_depth,
                        ]
                    )

                payload = {
                    "function_id": None,
                    "function_name": str(getattr(raw_graph, "funcname", "unknown") or "unknown"),
                    "source": "gemini",
                    "source_dataset": "gemini",
                    "project_name": default_project,
                    "binary_name": default_binary,
                    "binary_path": str(cfg_path),
                    "compiler": default_compiler,
                    "optimization_level": default_opt,
                    "node_features": node_features,
                    "edge_index": [src, dst],
                    "num_nodes": len(node_features),
                }

                if self._save_external_payload(payload, source="gemini"):
                    converted += 1
                    if converted % max(1, self.progress_interval) == 0:
                        self._log(f"Gemini function progress: converted={converted} from {cfg_path.name}")
                else:
                    skipped += 1
            except Exception:
                skipped += 1

        return converted, skipped

    def _convert_trex_binary(self, binary_path: Path) -> Tuple[int, int]:
        converted = 0
        skipped = 0
        self._log(f"Analyzing Trex binary: {binary_path}")

        graph_store = MemoryGraphStore()
        agent = StaticAgent(graph_store)
        agent.run(str(binary_path), verbose=False)

        trex_meta = self._extract_trex_metadata(binary_path)
        for func in graph_store.fetch_functions():
            try:
                func_addr = func.get("addr")
                if func_addr is None:
                    skipped += 1
                    continue

                blocks = graph_store.fetch_basic_blocks(func_addr)
                edges = graph_store.fetch_flow_edges(func_addr)
                if not blocks:
                    skipped += 1
                    continue

                payload = {
                    "function_id": None,
                    "function_name": func.get("name", f"sub_{int(func_addr):x}"),
                    "source": "trex",
                    "source_dataset": "trex",
                    "project_name": trex_meta["project_name"],
                    "binary_name": binary_path.name,
                    "binary_path": str(binary_path),
                    "compiler": trex_meta["compiler"],
                    "optimization_level": trex_meta["optimization_level"],
                    "node_features": self._build_node_features(graph_store, blocks, edges),
                    "edge_index": self._build_edge_index(blocks, edges),
                    "num_nodes": len(blocks),
                }

                if self._save_external_payload(payload, source="trex"):
                    converted += 1
                    if converted % max(1, self.progress_interval) == 0:
                        self._log(f"Trex function progress: converted={converted} from {binary_path.name}")
                else:
                    skipped += 1
            except Exception:
                skipped += 1

        return converted, skipped

    @staticmethod
    def _extract_trex_metadata(binary_path: Path) -> Dict[str, str]:
        # Typical path: external/trex/<arch>/<project>-<version>-O2/<binary>
        parent = binary_path.parent.name
        parts = parent.split("-")
        project_name = parent
        opt = "unknown"
        if parts and re.match(r"^O[0-3]$", parts[-1]):
            opt = parts[-1]
            project_name = "-".join(parts[:-1]) if len(parts) > 1 else parent

        compiler = "unknown"
        if "clang" in parent:
            compiler = "clang"
        elif "gcc" in parent:
            compiler = "gcc"

        return {
            "project_name": project_name,
            "compiler": compiler,
            "optimization_level": opt,
        }

    def _parse_external_graph_file(self, path: Path) -> Iterable[Dict[str, Any]]:
        suffix = path.suffix.lower()

        if suffix == ".pt" and _TORCH_AVAILABLE:
            try:
                payload = torch.load(path, map_location="cpu")
            except Exception:
                return []
            return self._extract_graph_records(payload)

        if suffix == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return []
            return self._extract_graph_records(payload)

        if suffix == ".jsonl":
            records: List[Dict[str, Any]] = []
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            records.extend(self._extract_graph_records(json.loads(line)))
                        except Exception:
                            continue
            except Exception:
                return []
            return records

        return []

    @staticmethod
    def _extract_graph_records(payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, dict):
            if isinstance(payload.get("graphs"), list):
                return [x for x in payload["graphs"] if isinstance(x, dict)]
            if isinstance(payload.get("data"), list):
                return [x for x in payload["data"] if isinstance(x, dict)]
            if "node_features" in payload or "x" in payload:
                return [payload]
            return []

        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]

        return []

    def _coerce_to_graph_payload(self, record: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
        node_features = record.get("node_features")
        if node_features is None:
            node_features = record.get("x")
        if node_features is None:
            return None

        edge_index = record.get("edge_index")
        if edge_index is None:
            edges = record.get("edges")
            if isinstance(edges, list):
                src: List[int] = []
                dst: List[int] = []
                for edge in edges:
                    if isinstance(edge, (list, tuple)) and len(edge) >= 2:
                        src.append(int(edge[0]))
                        dst.append(int(edge[1]))
                edge_index = [src, dst]

        if edge_index is None:
            edge_index = [[], []]

        coerced_nodes = self._coerce_node_features(node_features)
        if not coerced_nodes:
            return None

        coerced_edges = self._coerce_edge_index(edge_index)
        function_name = record.get("function_name") or record.get("name") or "unknown"
        function_id = record.get("function_id") or record.get("id")
        project_name = record.get("project_name") or record.get("project") or source
        compiler = record.get("compiler") or "unknown"
        optimization_level = record.get("optimization_level") or record.get("opt") or "unknown"
        binary_name = record.get("binary_name") or record.get("binary") or "unknown"

        return {
            "function_id": str(function_id) if function_id is not None else None,
            "function_name": str(function_name),
            "source": source,
            "source_dataset": source,
            "project_name": str(project_name),
            "binary_name": str(binary_name),
            "binary_path": str(record.get("binary_path") or "unknown"),
            "compiler": str(compiler),
            "optimization_level": str(optimization_level),
            "node_features": coerced_nodes,
            "edge_index": coerced_edges,
            "num_nodes": len(coerced_nodes),
        }

    @staticmethod
    def _coerce_node_features(value: Any) -> List[List[float]]:
        if hasattr(value, "tolist"):
            value = value.tolist()
        if not isinstance(value, list):
            return []
        if value and all(isinstance(x, (int, float)) for x in value):
            return [[float(x) for x in value]]

        output: List[List[float]] = []
        for row in value:
            if not isinstance(row, list):
                return []
            output.append([float(x) for x in row])
        return output

    @staticmethod
    def _coerce_edge_index(value: Any) -> List[List[int]]:
        if hasattr(value, "tolist"):
            value = value.tolist()
        if not isinstance(value, list) or len(value) != 2:
            return [[], []]
        src = [int(x) for x in value[0]] if isinstance(value[0], list) else []
        dst = [int(x) for x in value[1]] if isinstance(value[1], list) else []
        if len(src) != len(dst):
            size = min(len(src), len(dst))
            src = src[:size]
            dst = dst[:size]
        return [src, dst]

    # ---------------------------------------------------------------
    # Step 6/8/9/10: normalization, merge weighting, cleaning, metadata
    # ---------------------------------------------------------------

    def normalize_and_fuse_graphs(self, min_nodes: int = 3) -> Dict[str, Any]:
        self.ensure_layout()
        if not _TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required to serialize graph files")

        self._log("Starting graph normalization and fusion")

        if not self.minimal_mode:
            self._clear_existing_graph_outputs()

        raw_paths = sorted(self.raw_graphs_dir.glob("*.pt"))
        normalized_candidates: List[Dict[str, Any]] = []
        duplicates = 0
        corrupted = 0
        filtered_small = 0
        seen_hashes: set[str] = set()
        processed_ids = self._load_processed_ids() if self.minimal_mode else set()

        def _iter_payloads(paths: List[Path]) -> Iterable[Tuple[Path, Optional[Dict[str, Any]]]]:
            if self.normalize_workers <= 1:
                for p in paths:
                    try:
                        payload = torch.load(p, map_location="cpu")
                    except Exception:
                        payload = None
                    yield p, payload if isinstance(payload, dict) else None
                return

            with concurrent.futures.ProcessPoolExecutor(max_workers=self.normalize_workers) as pool:
                future_map = {
                    pool.submit(_load_raw_payload_worker, str(p)): p for p in paths
                }
                for fut in concurrent.futures.as_completed(future_map):
                    p = future_map[fut]
                    try:
                        payload = fut.result()
                    except Exception:
                        payload = None
                    yield p, payload if isinstance(payload, dict) else None

        for idx_path, (path, payload) in enumerate(_iter_payloads(raw_paths), start=1):
            if payload is None:
                corrupted += 1
                continue

            existing_id = str(payload.get("function_id") or path.stem)
            if self.minimal_mode and existing_id in processed_ids and (self.graphs_dir / f"{existing_id}.pt").exists():
                continue

            normalized = self._coerce_to_graph_payload(payload if isinstance(payload, dict) else {}, source=str(payload.get("source", "unknown")) if isinstance(payload, dict) else "unknown")
            if not normalized:
                corrupted += 1
                continue

            if normalized["num_nodes"] < min_nodes:
                filtered_small += 1
                continue

            dup_key = self._graph_fingerprint(normalized)
            if dup_key in seen_hashes:
                duplicates += 1
                continue
            seen_hashes.add(dup_key)
            normalized_candidates.append(normalized)
            if idx_path % max(1, self.progress_interval) == 0:
                self._log(
                    "Normalize progress: "
                    f"seen={idx_path} kept={len(normalized_candidates)} dup={duplicates} corrupt={corrupted} filtered={filtered_small}"
                )

        if self.max_total_graphs is not None and len(normalized_candidates) > self.max_total_graphs:
            normalized_candidates = self._sample_candidates(normalized_candidates, self.max_total_graphs, self.sampling_mode)
            self._log(
                f"Sampling applied: mode={self.sampling_mode} selected={len(normalized_candidates)}"
            )

        self._apply_feature_minmax_normalization(normalized_candidates)

        index_entries: List[Dict[str, Any]] = []
        for idx, graph in enumerate(normalized_candidates, start=1):
            function_id = graph.get("function_id") or f"func_{idx:08d}"
            graph["function_id"] = function_id
            graph["num_nodes"] = len(graph["node_features"])

            graph_path = self.graphs_dir / f"{function_id}.pt"
            torch.save(graph, graph_path)
            if self.minimal_mode:
                processed_ids.add(function_id)

            index_entries.append(
                {
                    "function_id": function_id,
                    "function_name": graph.get("function_name", "unknown"),
                    "source_dataset": graph.get("source", graph.get("source_dataset", "unknown")),
                    "binary_name": graph.get("binary_name", "unknown"),
                    "project_name": graph.get("project_name", "unknown"),
                    "compiler": graph.get("compiler", "unknown"),
                    "optimization_level": graph.get("optimization_level", "unknown"),
                    "graph_path": str(graph_path),
                    "num_nodes": graph.get("num_nodes", 0),
                }
            )

        weights = MINIMAL_MERGE_WEIGHTS if self.minimal_mode else MERGE_WEIGHTS
        weighted_ids = self._build_weighted_index(index_entries, weights=weights)
        pair_entries = self._build_triplet_pairs(index_entries, weighted_ids, max_pairs=self.pair_limit)

        self._write_json(self.metadata_dir / "index.json", index_entries)
        self._write_json(self.metadata_dir / "weighted_index.json", weighted_ids)
        self._write_json(self.pairs_dir / "train_pairs.json", pair_entries)
        if self.minimal_mode:
            self._save_processed_ids(processed_ids)

        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "raw_graphs_seen": len(raw_paths),
            "normalized_graphs": len(index_entries),
            "duplicates_removed": duplicates,
            "corrupted_removed": corrupted,
            "min_node_filtered": filtered_small,
            "pair_count": len(pair_entries),
            "targets": DATASET_SIZE_TARGETS,
            "weights": weights,
        }
        self._write_json(self.metadata_dir / "dataset_summary.json", summary)
        self._log(
            f"Normalization complete: kept={len(index_entries)} pairs={len(pair_entries)} duplicates={duplicates}"
        )
        return summary

    @staticmethod
    def _graph_fingerprint(graph: Dict[str, Any]) -> str:
        rounded_nodes: List[List[float]] = []
        for row in graph.get("node_features", []):
            rounded_nodes.append([round(float(x), 6) for x in row])
        edge_index = graph.get("edge_index", [[], []])
        src = edge_index[0] if isinstance(edge_index, list) and len(edge_index) == 2 else []
        dst = edge_index[1] if isinstance(edge_index, list) and len(edge_index) == 2 else []
        edge_pairs = sorted((int(a), int(b)) for a, b in zip(src, dst))
        digest_input = json.dumps({"nodes": rounded_nodes, "edges": edge_pairs}, sort_keys=True).encode("utf-8")
        return hashlib.sha1(digest_input).hexdigest()

    @staticmethod
    def _apply_feature_minmax_normalization(graphs: List[Dict[str, Any]]) -> None:
        if not graphs:
            return

        first = graphs[0].get("node_features", [])
        if not first or not isinstance(first[0], list):
            return

        feature_dim = len(first[0])
        mins = [float("inf")] * feature_dim
        maxs = [float("-inf")] * feature_dim

        for graph in graphs:
            for row in graph.get("node_features", []):
                if len(row) != feature_dim:
                    continue
                for i, value in enumerate(row):
                    value = float(value)
                    if value < mins[i]:
                        mins[i] = value
                    if value > maxs[i]:
                        maxs[i] = value

        for graph in graphs:
            normalized_rows: List[List[float]] = []
            for row in graph.get("node_features", []):
                if len(row) != feature_dim:
                    continue
                out_row: List[float] = []
                for i, value in enumerate(row):
                    denom = maxs[i] - mins[i]
                    if denom <= 1e-12:
                        out_row.append(0.0)
                    else:
                        out_row.append((float(value) - mins[i]) / denom)
                normalized_rows.append(out_row)
            graph["node_features"] = normalized_rows

    def _build_weighted_index(self, entries: List[Dict[str, Any]], weights: Dict[str, float]) -> List[Dict[str, Any]]:
        if not entries:
            return []

        source_to_entries: Dict[str, List[Dict[str, Any]]] = {}
        for entry in entries:
            source = str(entry.get("source_dataset", "unknown")).lower()
            source_to_entries.setdefault(source, []).append(entry)

        target_total = len(entries)
        selected: List[Dict[str, Any]] = []
        rng = random.Random(1337)

        for source_name, weight in weights.items():
            pool = source_to_entries.get(source_name, [])
            if not pool:
                continue
            wanted = max(1, int(round(target_total * weight)))
            if len(pool) >= wanted:
                picked = rng.sample(pool, wanted)
            else:
                picked = list(pool)
                while len(picked) < wanted:
                    picked.append(rng.choice(pool))
            selected.extend(
                {
                    "function_id": item["function_id"],
                    "source_dataset": item["source_dataset"],
                    "graph_path": item["graph_path"],
                }
                for item in picked
            )

        if not selected:
            return []

        while len(selected) < target_total:
            selected.append(rng.choice(selected))
        return selected[:target_total]

    def _build_triplet_pairs(
        self,
        entries: List[Dict[str, Any]],
        weighted_ids: List[Dict[str, Any]],
        max_pairs: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        if not entries:
            return []

        by_id = {entry["function_id"]: entry for entry in entries}
        candidate_entries = [by_id[item["function_id"]] for item in weighted_ids if item.get("function_id") in by_id]
        if not candidate_entries:
            candidate_entries = entries

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for entry in candidate_entries:
            key = self._canonical_function_name(entry.get("function_name"))
            groups.setdefault(key, []).append(entry)

        all_entries = list(candidate_entries)
        rng = random.Random(1337)
        triplets: List[Dict[str, str]] = []

        for key, group in groups.items():
            if len(group) < 2:
                continue

            for anchor in group:
                positive_candidates = [
                    g
                    for g in group
                    if g["function_id"] != anchor["function_id"]
                    and (
                        g.get("compiler") != anchor.get("compiler")
                        or g.get("optimization_level") != anchor.get("optimization_level")
                        or g.get("binary_name") != anchor.get("binary_name")
                    )
                ]
                if not positive_candidates:
                    positive_candidates = [g for g in group if g["function_id"] != anchor["function_id"]]
                if not positive_candidates:
                    continue

                same_project_negative = [
                    e for e in all_entries if e.get("project_name") == anchor.get("project_name") and self._canonical_function_name(e.get("function_name")) != key
                ]
                cross_project_negative = [
                    e for e in all_entries if e.get("project_name") != anchor.get("project_name")
                ]
                cross_dataset_negative = [
                    e for e in all_entries if e.get("source_dataset") != anchor.get("source_dataset")
                ]

                negative_pool = same_project_negative or cross_project_negative or cross_dataset_negative
                if not negative_pool:
                    continue

                positive = rng.choice(positive_candidates)
                negative = rng.choice(negative_pool)

                triplets.append(
                    {
                        "anchor": anchor["function_id"],
                        "positive": positive["function_id"],
                        "negative": negative["function_id"],
                    }
                )
                if max_pairs is not None and len(triplets) >= max_pairs:
                    return triplets

        return triplets

    def _sample_candidates(
        self,
        candidates: List[Dict[str, Any]],
        max_graphs: int,
        mode: str,
    ) -> List[Dict[str, Any]]:
        if len(candidates) <= max_graphs:
            return candidates

        rng = random.Random(1337)
        sampled: List[Dict[str, Any]] = []
        mode = mode.lower().strip()

        if mode == "random":
            return rng.sample(candidates, max_graphs)

        if mode == "per-dataset":
            groups: Dict[str, List[Dict[str, Any]]] = {}
            for item in candidates:
                groups.setdefault(str(item.get("source_dataset", "unknown")), []).append(item)
            quota = max(1, max_graphs // max(1, len(groups)))
            for group in groups.values():
                pick = group if len(group) <= quota else rng.sample(group, quota)
                sampled.extend(pick)
        elif mode == "per-project":
            groups = {}
            for item in candidates:
                groups.setdefault(str(item.get("project_name", "unknown")), []).append(item)
            quota = max(1, max_graphs // max(1, len(groups)))
            for group in groups.values():
                pick = group if len(group) <= quota else rng.sample(group, quota)
                sampled.extend(pick)
        else:
            return rng.sample(candidates, max_graphs)

        if len(sampled) < max_graphs:
            pool = [item for item in candidates if item not in sampled]
            need = min(max_graphs - len(sampled), len(pool))
            sampled.extend(rng.sample(pool, need))

        return sampled[:max_graphs]

    # ---------------------------------------------------------------
    # End-to-end pipeline
    # ---------------------------------------------------------------

    def run_full_pipeline(
        self,
        projects: Optional[Sequence[str]] = None,
        jobs: int = 4,
        synthetic_per_category: int = 8,
        include_compiled_for_analysis: bool = False,
        external_sources: Optional[Sequence[str]] = None,
        max_opensource_binaries: Optional[int] = None,
    ) -> Dict[str, Any]:
        self.ensure_layout()

        self.collect_open_source_code(projects=projects)
        self.generate_synthetic_programs(programs_per_category=synthetic_per_category)
        self.compile_open_source_matrix(projects=projects, compile_variants=DEFAULT_COMPILE_VARIANTS, jobs=jobs)
        self.compile_synthetic_matrix(compile_variants=DEFAULT_COMPILE_VARIANTS)
        self.strip_compiled_binaries()
        self.build_raw_graphs_from_binaries(
            include_compiled=include_compiled_for_analysis,
            include_stripped=True,
            max_binaries=max_opensource_binaries,
        )
        self.integrate_external_datasets(sources=external_sources)
        return self.normalize_and_fuse_graphs(min_nodes=3)


def _load_raw_payload_worker(path_str: str) -> Optional[Dict[str, Any]]:
    try:
        import torch as _torch

        payload = _torch.load(path_str, map_location="cpu")
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M0ST unified dataset builder")
    parser.add_argument("--root", default="data/datasets", help="Dataset root directory")
    parser.add_argument("--projects", default="", help="Comma-separated project names")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--synthetic-per-category", type=int, default=8)
    parser.add_argument("--include-compiled-for-analysis", action="store_true")
    parser.add_argument(
        "--external-sources",
        default="safe,gemini",
        help="Comma-separated external datasets to ingest (safe,trex,gemini)",
    )
    parser.add_argument(
        "--external-only",
        action="store_true",
        help="Run only external ingest + normalize stages",
    )
    parser.add_argument("--min-nodes", type=int, default=3, help="Minimum node threshold for normalization")
    parser.add_argument(
        "--reset-raw-graphs",
        action="store_true",
        help="Clear data/datasets/raw_graphs before external ingest",
    )
    parser.add_argument(
        "--reset-normalized-graphs",
        action="store_true",
        help="Clear data/datasets/graphs before normalization",
    )
    parser.add_argument("--safe-max-functions", type=int, default=0, help="Cap SAFE functions per DB (0 = no cap)")
    parser.add_argument("--gemini-max-graphs", type=int, default=0, help="Cap Gemini graphs per CFG file (0 = no cap)")
    parser.add_argument("--trex-max-binaries", type=int, default=0, help="Cap Trex binaries to analyze (0 = no cap)")
    parser.add_argument("--max-opensource-binaries", type=int, default=0, help="Cap open-source binaries analyzed (0 = no cap)")
    parser.add_argument("--max-total-graphs", type=int, default=30000, help="Cap total normalized graphs (0 = no cap)")
    parser.add_argument(
        "--sampling-mode",
        default="random",
        choices=["random", "per-project", "per-dataset"],
        help="Sampling strategy when max-total-graphs is set",
    )
    parser.add_argument("--pair-limit", type=int, default=50000, help="Maximum triplet count")
    parser.add_argument("--normalize-workers", type=int, default=1, help="Worker processes for payload loading")
    parser.add_argument("--minimal-mode", action="store_true", help="Enable fast minimal pipeline mode")
    parser.add_argument("--verbose", action="store_true", help="Print heartbeat progress logs")
    parser.add_argument("--progress-interval", type=int, default=250, help="Progress log interval")
    return parser


def _parse_csv(value: str) -> List[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    builder = DatasetBuilder(root_dir=args.root)
    builder.safe_max_functions = args.safe_max_functions or None
    builder.gemini_max_graphs = args.gemini_max_graphs or None
    builder.trex_max_binaries = args.trex_max_binaries or None
    builder.verbose = args.verbose
    builder.progress_interval = max(1, args.progress_interval)
    builder.max_total_graphs = args.max_total_graphs or None
    builder.sampling_mode = args.sampling_mode
    builder.pair_limit = max(1, args.pair_limit)
    builder.normalize_workers = max(1, args.normalize_workers)
    builder.minimal_mode = bool(args.minimal_mode)
    selected_projects = _parse_csv(args.projects) if args.projects else None
    selected_external_sources = _parse_csv(args.external_sources) if args.external_sources else ["safe", "gemini"]

    if builder.minimal_mode and "trex" in selected_external_sources:
        selected_external_sources = [s for s in selected_external_sources if s != "trex"]

    if args.external_only:
        if args.reset_raw_graphs:
            builder._clear_existing_raw_graphs()
        if args.reset_normalized_graphs:
            builder._clear_existing_graph_outputs()
        external_summary = builder.integrate_external_datasets(sources=selected_external_sources)
        normalize_summary = builder.normalize_and_fuse_graphs(min_nodes=max(1, args.min_nodes))
        summary = {
            "external": external_summary,
            "normalize": normalize_summary,
        }
        print(json.dumps(summary, indent=2))
        return 0

    summary = builder.run_full_pipeline(
        projects=selected_projects,
        jobs=args.jobs,
        synthetic_per_category=args.synthetic_per_category,
        include_compiled_for_analysis=args.include_compiled_for_analysis,
        external_sources=selected_external_sources,
        max_opensource_binaries=args.max_opensource_binaries or None,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
