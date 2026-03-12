# M0ST — Technologies and Concepts

This document describes every significant technology, library, and concept used in the M0ST platform: what it is, where it appears in the codebase, and how it is used.

---

## Table of Contents

1. [Core Language and Runtime](#1-core-language-and-runtime)
2. [Binary Analysis Tools](#2-binary-analysis-tools)
3. [Graph Neural Networks](#3-graph-neural-networks)
4. [Large Language Models](#4-large-language-models)
5. [Constraint Solving and Formal Verification](#5-constraint-solving-and-formal-verification)
6. [Dynamic Analysis](#6-dynamic-analysis)
7. [Storage and Persistence](#7-storage-and-persistence)
8. [Program Knowledge Graph](#8-program-knowledge-graph)
9. [CLI and User Interface](#9-cli-and-user-interface)
10. [Orchestration and Agent Architecture](#10-orchestration-and-agent-architecture)
11. [Plugin System](#11-plugin-system)
12. [Containerisation](#12-containerisation)
13. [Key Concepts and Algorithms](#13-key-concepts-and-algorithms)

---

## 1. Core Language and Runtime

### Python 3.10+

- **What:** General-purpose programming language.
- **Where:** Entire codebase (`main.py`, all modules, agents, CLI).
- **How:** M0ST is a Python application. Python's dynamic nature allows the plugin system to load modules at runtime, and its `typing` module is used extensively for interface clarity. Python 3.10+ features (structural pattern matching, improved type hints) are used in agent logic.

### PyYAML

- **What:** YAML parser/emitter for Python.
- **Where:** `core/config.py`
- **How:** The `config.yml` file is parsed at startup with `yaml.safe_load()`. All platform configuration (LLM provider, tool paths, pipeline parameters) is loaded from YAML into a global config object accessed across all agents.

### NetworkX

- **What:** Python library for graph construction and analysis.
- **Where:** `knowledge/program_graph/`, `storage/memory_graph_store.py`, `analysis/complexity.py`
- **How:** The in-memory Program Knowledge Graph (PKG) is implemented as a `networkx.MultiDiGraph`. Functions, basic blocks, instructions, variables, and other program entities are nodes; control-flow edges, call edges, and data-flow edges are directed edges with type annotations. NetworkX provides traversal, shortest-path, and subgraph extraction algorithms used by agents.

### Pygments

- **What:** Python syntax highlighting library.
- **Where:** `ui/cli.py`
- **How:** When printing disassembly or pseudocode in the CLI, Pygments tokenises and colourises the output using ANSI escape codes (assembly or C lexers), making the output easier to read in terminals that support colour.

---

## 2. Binary Analysis Tools

### radare2

- **What:** Open-source reverse engineering framework for disassembly, CFG recovery, and binary inspection.
- **Where:** `ai_security_agents/static_agent.py`, `ai_security_agents/pseudocode_agent.py`
- **How:**
  - `StaticAgent` calls radare2 via `r2pipe` to open a binary, run analysis (`aaa`), and extract the full function list (`aflj`), basic blocks per function (`abj`), instructions per block (`pdj`), and cross-references (`axffj`). All data is stored in the PKG.
  - `PseudocodeAgent` uses radare2's built-in decompiler (`pdg`/`pdc`) as a fallback when Ghidra is unavailable.
  - When verbose mode is off, `e bin.verbose=false` and `e log.level=0` are applied immediately after `r2pipe.open()` to suppress radare2's INFO/WARN output from reaching the terminal.

### r2pipe

- **What:** Python bindings for radare2 — lets Python code issue r2 commands and receive JSON responses.
- **Where:** `ai_security_agents/static_agent.py`, `ai_security_agents/pseudocode_agent.py`
- **How:** `r2pipe.open(binary_path, radare2home=...)` returns an `r2` handle. Agents call `r2.cmdj(command)` for JSON output and `r2.cmd(command)` for raw output. The `radare2home` parameter points to a custom radare2 install directory when the binary is not on `PATH`.

### Ghidra

- **What:** NSA open-source software reverse engineering tool with a powerful headless decompiler.
- **Where:** `ai_security_agents/pseudocode_agent.py`
- **How:** When configured via `tools.ghidra_path`, `PseudocodeAgent` invokes Ghidra's `analyzeHeadless` script as a subprocess to decompile a function to C pseudocode. The output is captured, normalised, and stored in the PKG as a `PSEUDOCODE` annotation. This produces significantly higher-quality pseudocode than radare2's built-in decompiler.

---

## 3. Graph Neural Networks

### PyTorch

- **What:** Deep learning framework providing automatic differentiation and tensor operations.
- **Where:** `ai_engine/gnn_models/`, `ai_engine/embedding_models/`
- **How:** GNN model weights are stored as PyTorch tensors. The forward pass of GAT/GraphSAGE/GINE models is implemented using PyTorch operations. If PyTorch is not installed, M0ST falls back to hand-crafted feature vectors.

### PyTorch Geometric (torch-geometric)

- **What:** Graph deep learning library built on PyTorch, providing efficient GNN layer implementations.
- **Where:** `ai_engine/gnn_models/`, `ai_engine/embedding_models/`
- **How:** `torch_geometric.nn.GATConv`, `SAGEConv`, and `GINEConv` layers are used to build three GNN architectures. Control-flow graphs extracted by `StaticAgent` are converted to `torch_geometric.data.Data` objects (node feature matrix + edge index tensor) and fed through the GNN to produce per-function embedding vectors of dimension 64.

### Graph Attention Network (GAT)

- **What:** A GNN architecture that uses attention mechanisms to weight neighbour aggregation.
- **Where:** `ai_engine/gnn_models/` (default architecture)
- **How:** Each basic block node in the CFG is represented by an opcode histogram feature vector (12 opcode categories + structural features). The GAT applies multi-head attention over the CFG structure, producing a graph-level embedding via mean pooling. This embedding captures the structural "shape" of a function independent of symbol names.

### GraphSAGE

- **What:** A GNN that samples and aggregates features from node neighbourhoods.
- **Where:** `ai_engine/gnn_models/` (selectable via `gnn.architecture: graphsage`)
- **How:** Alternative to GAT when attention overhead is too high. Uses mean aggregation over sampled neighbourhoods. Suitable for larger binaries with dense call graphs.

### GINE (Graph Isomorphism Network with Edge features)

- **What:** A GNN that incorporates edge features into message passing, making it more expressive.
- **Where:** `ai_engine/gnn_models/` (selectable via `gnn.architecture: gine`)
- **How:** Uses edge type features (`CFG_FLOW`, `CALL`, etc.) in addition to node features, allowing the model to distinguish paths from calls in the same embedding.

### Binary Embedding Engine

- **What:** M0ST's pipeline that converts a function's CFG into a searchable embedding vector.
- **Where:** `ai_engine/embedding_models/__init__.py`
- **How:** For each function: (1) fetch basic blocks from PKG, (2) build opcode histogram per block, (3) construct PyG graph, (4) run GNN forward pass, (5) mean-pool node embeddings → function-level vector stored in `EmbeddingStore`. Cosine similarity search over stored embeddings enables the `find similar` CLI command.

---

## 4. Large Language Models

### OpenAI API (openai SDK)

- **What:** Client library for OpenAI's GPT-series and compatible APIs.
- **Where:** `ai_security_agents/llm_agent.py`
- **How:** `LLMAgent._query_openai()` calls `client.chat.completions.create()` with `response_format={"type": "json_object"}` to enforce structured JSON output. The system prompt instructs the LLM to act as a binary analysis expert and always respond with valid JSON. This is used for function naming, type inference, vulnerability detection, and natural language summaries.

### Anthropic Claude (anthropic SDK)

- **What:** Client library for Anthropic's Claude family of models.
- **Where:** `ai_security_agents/llm_agent.py`
- **How:** `LLMAgent._query_anthropic()` uses `client.messages.create()`. Since Anthropic's API doesn't support `response_format`, the JSON constraint is enforced via the system prompt and a `_extract_json()` post-processing step with 3 retry attempts.

### Mistral AI (mistralai SDK)

- **What:** Client library for Mistral's hosted models.
- **Where:** `ai_security_agents/llm_agent.py`
- **How:** Same pattern as Anthropic — system-prompt-level JSON enforcement with post-processing extraction.

### Ollama / Local LLM

- **What:** Self-hosted LLM server that exposes an OpenAI-compatible API endpoint.
- **Where:** `ai_security_agents/llm_agent.py` (via `llm.provider: local` and `llm.base_url`)
- **How:** Uses the `openai` SDK pointed at `http://localhost:11434/v1`. This lets users run models like `llama3`, `mistral`, or `codellama` locally with zero data leaving the machine. Ideal for analysing sensitive or classified binaries.

### Prompt Engineering

- **What:** Structured prompts that guide LLM output format and content.
- **Where:** `ai_security_agents/llm_agent.py` (`build_prompt()`), `ai_security_agents/llm_semantic_agent.py`
- **How:** `build_prompt()` assembles a task-specific prompt from: (1) instruction/task description, (2) disassembly listing, (3) pseudocode if available, (4) GNN embedding similarity results, (5) metadata (basic block count, instruction count, etc.). Different `task` keys (`name_function`, `infer_types`, `explain_function`, `analyst_query`, etc.) produce different prompt structures tailored to what the LLM needs to reason about.

### JSON Extraction and Retry Logic

- **What:** Robust parsing of LLM responses that may be malformed JSON.
- **Where:** `ai_security_agents/llm_agent.py` (`_extract_json()`, `_query_json()`)
- **How:** `_query_json()` first tries direct `json.loads()`. If that fails, it strips markdown code fences, extracts the first `{...}` block via regex, and retries up to 3 times with an error feedback prompt injected. This handles LLMs that wrap JSON in markdown or add prose before/after the JSON object.

---

## 5. Constraint Solving and Formal Verification

### Z3 SMT Solver (z3-solver)

- **What:** Microsoft Research's Theorem Prover and Satisfiability Modulo Theories solver.
- **Where:** `ai_security_agents/z3_agent.py`
- **How:** `Z3Agent` uses Z3 to verify safety properties of program paths extracted from the PKG. For a given function, it encodes basic block constraints (e.g., bounds on loop variables, pointer dereference conditions) as Z3 formulas and checks satisfiability to detect potentially unsafe paths. Falls back gracefully if `z3-solver` is not installed.

### VerifierAgent

- **What:** M0ST's agent that checks structural correctness of the CFG.
- **Where:** `ai_security_agents/verifier_agent.py`
- **How:** After `StaticAgent` populates the PKG, `VerifierAgent` checks that every `CFG_FLOW` edge is consistent (no orphaned basic blocks, no edges to non-existent blocks). It also flags unreachable blocks — a common artefact of compiler optimisation or obfuscation. Results are stored as PKG annotations.

---

## 6. Dynamic Analysis

### GDB (GNU Debugger)

- **What:** The standard Unix debugger for source and assembly-level program inspection.
- **Where:** `ai_security_agents/dynamic_agent.py` (GDB strategy)
- **How:** `DynamicAgent` runs the target binary under GDB via `pygdbmi`. It sets breakpoints at every function entry point discovered in the PKG, records register states and system call sequences during execution, and stores them as `RuntimeTrace` nodes in the PKG. Dynamic traces can reveal code paths not visible to static analysis (e.g., unpacked code, JIT-generated code).

### pygdbmi

- **What:** Python library providing a programmatic machine-readable interface to GDB.
- **Where:** `ai_security_agents/dynamic_agent.py`
- **How:** `pygdbmi.GdbController` spawns a GDB process and communicates via the GDB Machine Interface (MI) protocol. JSON-structured responses are parsed to extract register values, breakpoint hits, and memory reads without screen-scraping GDB's terminal output.

### WinDbg / cdb (Windows)

- **What:** Microsoft's user- and kernel-mode debugger for Windows.
- **Where:** `ai_security_agents/dynamic_agent.py` (WinDbg strategy)
- **How:** When `dynamic.strategy: windbg` is set (or auto-detected on Windows), `DynamicAgent` invokes `cdb.exe` with scripted commands to trace Windows PE binaries. This enables dynamic analysis of Windows malware directly on Windows without needing WSL or a VM.

### x64dbg

- **What:** Open-source 64-bit Windows debugger.
- **Where:** `ai_security_agents/dynamic_agent.py` (x64dbg strategy)
- **How:** Alternative Windows debugger. `DynamicAgent` drives it via its scripting interface when the path is configured via `tools.x64dbg_path`.

### Docker (dynamic sandbox)

- **What:** Containerisation platform providing isolated execution environments.
- **Where:** `ai_security_agents/dynamic_agent.py` (Docker strategy), `docker/`
- **How:** When `dynamic.strategy: docker` is configured, `DynamicAgent` runs the target binary inside a container (image `m0st/gdb-trace:latest` by default) with GDB pre-installed. This provides safe isolation for running untrusted or potentially malicious samples. The container's GDB traces are retrieved and imported into the PKG.

---

## 7. Storage and Persistence

### SQLite (via Python `sqlite3`)

- **What:** Serverless embedded SQL database.
- **Where:** `storage/sqlite_store.py`
- **How:** Analysis results are persisted in a local SQLite database (default: `storage/metadata.db`). The schema stores function metadata, analysis results, symbol mappings, and plugin outputs keyed by binary SHA-256 hash. This allows results to be reloaded across sessions without re-running the full pipeline.

### In-Memory Graph Store

- **What:** NetworkX-based in-memory graph structure as the primary working store during a session.
- **Where:** `storage/memory_graph_store.py`
- **How:** All agents read and write to this store during a pipeline run. The `MemoryGraphStore` exposes a typed API (`add_function`, `add_basic_block`, `add_instruction`, `add_edge`, `fetch_functions`, etc.) that wraps the underlying NetworkX graph. Since all operations are in-memory, agent coordination has microsecond latency.

### Snapshot System

- **What:** Save/load mechanism for analysis state.
- **Where:** `storage/snapshots.py`
- **How:** `SnapshotManager.save(name)` serialises the entire PKG (nodes, edges, annotations) plus the SQLite contents to a named snapshot file. `load(name)` restores the state. Snapshots are used to checkpoint long analyses and to compare analysis states before and after applying a patch.

---

## 8. Program Knowledge Graph

### PKG (Program Knowledge Graph)

- **What:** M0ST's unified intermediate representation — a single graph that captures all known facts about a program.
- **Where:** `knowledge/program_graph/__init__.py`
- **How:** Implemented as a `networkx.MultiDiGraph`. Every piece of information extracted by any agent is expressed as either a node or an edge in this graph. This means any agent can query any other agent's results by traversing the graph. There is no ad-hoc data passing between agents — they all read/write the PKG.

**Node types:**

| Node Type     | What it represents                          |
| ------------- | ------------------------------------------- |
| `FUNCTION`    | A discovered function (address, name, size) |
| `BASIC_BLOCK` | A basic block within a function             |
| `INSTRUCTION` | A single assembly instruction               |
| `VARIABLE`    | A local variable or argument                |
| `STRUCT`      | A recovered struct/data type                |
| `STRING`      | A string literal referenced by the program  |
| `IMPORT`      | An imported function or library             |
| `EMBEDDING`   | A stored embedding vector (GNN output)      |

**Edge types:**

| Edge Type       | What it represents                                  |
| --------------- | --------------------------------------------------- |
| `CALL`          | Direct function call                                |
| `CFG_FLOW`      | Control-flow edge between basic blocks              |
| `DATA_FLOW`     | Data dependency between variables/instructions      |
| `TYPE_RELATION` | Struct membership or type inheritance               |
| `USES_STRING`   | Function references a string literal                |
| `IMPORTS`       | Function uses an imported symbol                    |
| `TYPE_OF`       | Variable type annotation                            |
| `SIMILAR_TO`    | Two functions with high embedding cosine similarity |

### EmbeddingStore

- **What:** Key-value vector store for function embeddings.
- **Where:** `knowledge/embeddings/__init__.py`
- **How:** After the GNN produces an embedding for a function, it is stored in `EmbeddingStore` with the function address as key. `search_similar(vector, k=5)` performs a brute-force cosine similarity scan and returns the `k` most similar functions. Used by `find similar` CLI command and by the LLM agent (to add relevant function comparisons to prompts).

### SymbolDatabase

- **What:** Store for recovered function/variable names with confidence scores.
- **Where:** `knowledge/symbol_database/__init__.py`
- **How:** After `SymbolRecoveryEngine` predicts a function name, it is stored in `SymbolDatabase` with a confidence value (0.0–1.0) reflecting how the name was recovered (heuristic < embedding < LLM). Names are later used by `LLMSemanticAgent` when building prompts — higher-confidence names are shown to the LLM as grounding facts.

---

## 9. CLI and User Interface

### readline / pyreadline3

- **What:** GNU Readline (Linux) / pyreadline3 (Windows) — line-editing and history for interactive input.
- **Where:** `ui/cli.py`
- **How:** Enables tab-completion for M0ST commands and function addresses in the REPL. `readline.set_completer()` is bound to a completer function that provides context-aware suggestions (commands after empty input, hex addresses for commands that take an address argument). Arrow-key history navigation is available out of the box.

### difflib

- **What:** Python's built-in sequence comparison library.
- **Where:** `ui/cli.py`
- **How:** When a user types an unrecognised command, `difflib.get_close_matches()` compares the input against the full command list and suggests the closest match. For example, typing `lst funcs` produces a "Did you mean: list funcs?" suggestion.

### threading (spinner animation)

- **What:** Python's standard thread management.
- **Where:** `orchestration/master_agent.py` (pipeline quiet mode)
- **How:** When verbose mode is off, a background daemon thread runs a Braille-frame spinner animation (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) at 80ms per frame, printing `[Master] Analyzing functions ⠹ 4/12` to the terminal. The spinner shares a simple dict for `done`/`current`/`frame` state — no lock needed since only one writer exists.

### contextlib.redirect_stdout

- **What:** Python context manager that temporarily replaces `sys.stdout`.
- **Where:** `orchestration/master_agent.py`
- **How:** In quiet mode, agent `print()` calls are silenced by running agent code inside `contextlib.redirect_stdout(io.StringIO())`. This suppresses all Python-level print output without modifying agent code. (radare2 subprocess output is suppressed separately via `e log.level=0` at the r2 API level.)

### Paginated Help

- **What:** Category-based help system with indexed navigation.
- **Where:** `ui/cli.py` (`_print_help()`)
- **How:** `help` shows a structured index of command categories. `help <category>` (e.g., `help ai`, `help graph`, `help management`) shows the full command list for that category. `help all` prints everything at once. This replaces a flat text dump with a navigable reference.

---

## 10. Orchestration and Agent Architecture

### MasterAgent

- **What:** Top-level pipeline controller.
- **Where:** `orchestration/master_agent.py`
- **How:** `run_pipeline(binary_path, verbose=False)` executes the classical analysis sequence: static → heuristics → verify → GNN → dynamic → plugins → semantic → security modules → snapshot. Each stage is wrapped in try/except so a failing stage never aborts the rest. The `verbose` flag controls output verbosity and is propagated to all sub-agents.

### PlannerAgent

- **What:** Intelligent 13-stage coordinator that adds decision logic on top of the classical pipeline.
- **Where:** `orchestration/planner_agent.py`
- **How:** Implements `run_full_pipeline()` and per-function analysis methods (`ai_name`, `ai_explain`, `ai_types`, `ai_refine`, `ai_ask`, `find_similar`). Each stage checks conditions before invoking agents (e.g., `_should_run_dynamic()` checks if the binary has executable permissions and GDB is available; `_should_run_z3()` checks if the function has complex branching). Returns an `AnalysisResult` dataclass with aggregated outputs, timing, and stage completion metadata.

### Capability System

- **What:** A declarative access-control system for agent capabilities.
- **Where:** `core/capabilities.py`
- **How:** Each agent class has a `CAPABILITIES: frozenset[Capability]` class attribute declaring what it can do (e.g., `StaticAgent.CAPABILITIES = {Capability.STATIC_WRITE}`). Before invoking an agent, `enforce_capability(agent, capability)` checks that the agent has the required capability and raises a descriptive error if not. This prevents misconfiguration and documents the agent contract.

### Event Bus

- **What:** Lightweight publish-subscribe system for inter-agent communication.
- **Where:** `core/events.py`
- **How:** Agents publish events like `STATIC_ANALYSIS_COMPLETE` with payload data. Other agents can subscribe to these events. This decouples agents from each other — `StaticAgent` doesn't need to know which agents consume its output; it just publishes. The `MasterAgent` uses this for pipeline stage synchronisation with a configurable timeout.

---

## 11. Plugin System

### Dynamic Plugin Loader

- **What:** Runtime module discovery and loading.
- **Where:** `plugins/__init__.py` (`PluginManager`)
- **How:** `PluginManager` walks the `plugins/` directory tree at startup, imports every `.py` file that does not start with `_`, and registers all modules that expose an `analyze(graph_store, func_addr)` function. `run_all(graph_store, func_addr)` calls each plugin in sequence and merges results into a single findings dict that is stored as PKG annotations.

**Built-in plugins:**

| Plugin             | Location                           | What it does                                                                                      |
| ------------------ | ---------------------------------- | ------------------------------------------------------------------------------------------------- |
| `anti_debug`       | `plugins/anti_debug/anti_debug.py` | Detects anti-debugging API calls (IsDebuggerPresent, CheckRemoteDebuggerPresent, etc.)            |
| `crypto_detect`    | `plugins/crypto/crypto_detect.py`  | Identifies cryptographic constant patterns and API usage (AES, SHA, RSA indicators)               |
| `entropy_analysis` | `plugins/entropy/`                 | Computes Shannon entropy of instruction byte sequences — high entropy suggests packing/encryption |
| `magic_detect`     | `plugins/magic_pattern/`           | Matches file format magic byte sequences in data sections                                         |
| `string_decode`    | `plugins/string_decoder/`          | Identifies string-manipulation function patterns that may decode obfuscated strings               |

---

## 12. Containerisation

### Docker + Docker Compose

- **What:** Container platform for reproducible, isolated deployments.
- **Where:** `docker/backend.Dockerfile`, `docker/compose.yml`
- **How:** The `backend.Dockerfile` builds an image containing Python, required packages, and the M0ST codebase. `docker compose up` starts the container and mounts the local `data/` directory for sample storage. This is useful for (1) running M0ST in an isolated environment when analysing potentially malicious files, and (2) consistent CI/CD deployments.

---

## 13. Key Concepts and Algorithms

### Control-Flow Graph (CFG)

- **What:** A directed graph where nodes are basic blocks and edges represent possible execution flow.
- **Where:** Extracted by `StaticAgent`, stored in PKG, consumed by `GraphAgent`, `Z3Agent`, `PseudocodeAgent`, complexity analysis.
- **How:** `StaticAgent` calls `r2.cmdj("abj")` per function to get basic block boundaries, then `pdj` per block to get instructions, and reconstructs edges from jump/call destinations. The result is stored as `BASIC_BLOCK` nodes and `CFG_FLOW` edges in the PKG.

### Cyclomatic Complexity (McCabe Complexity)

- **What:** A software metric that counts the number of linearly independent paths through a function.
- **Where:** `analysis/complexity.py`, used via `complexity` CLI command
- **How:** For a function CFG with `E` edges, `N` nodes, and `P` components: `M = E - N + 2P`. Implemented by counting `CFG_FLOW` edges and `BASIC_BLOCK` nodes for each function in the PKG. High cyclomatic complexity (> 10) correlates with higher defect density and is used as a heuristic for identifying complex/suspicious functions.

### Shannon Entropy

- **What:** An information-theoretic measure of randomness in a byte sequence.
- **Where:** `plugins/entropy/`
- **How:** For a sequence of bytes, entropy is `H = -Σ p(b) log₂ p(b)` over all 256 byte values. High entropy (> 7.0 bits/byte) in a code section suggests packed or encrypted code — a common indicator of malware packers or obfuscators.

### Symbol Recovery (3-stage pipeline)

- **What:** Prediction of meaningful function names for stripped binaries.
- **Where:** `ai_engine/symbol_recovery/__init__.py`
- **How:**
  1. **Heuristic stage:** Pattern-match known function signatures (prologue patterns, import wrapper detection, size/structure heuristics) → low confidence.
  2. **Embedding stage:** Find functions with similar GNN embeddings that have known names (from a pre-labelled dataset) → medium confidence.
  3. **LLM stage:** Feed disassembly + pseudocode to the LLM with a naming prompt → high confidence.
     Each stage's result is stored in `SymbolDatabase` with its confidence score. The highest-confidence name wins.

### Obfuscation Detection

- **What:** Identification of anti-analysis techniques applied to a binary.
- **Where:** `security_modules/reverse_engineering/`
- **How:** The deobfuscation module checks for: control-flow flattening (dispatcher pattern), opaque predicates (constant conditionals), junk code insertion (dead code between real instructions), packer signatures, and VM-based obfuscation (dispatcher/handler patterns). Identified techniques are tagged in the PKG as function-level annotations.

### Risk Scoring (Malware Classification)

- **What:** 0.0 – 1.0 risk score per function based on API usage patterns.
- **Where:** `security_modules/ai_assisted_binary_analysis/malware_classification.py`
- **How:** An `IMPORT` edge weight matrix maps known suspicious API categories (process injection, anti-debug, network, registry persistence, etc.) to risk weights. The scorer sums weighted matches, normalises to [0.0, 1.0], and stores the result as a PKG annotation. The LLM is optionally consulted for functions with moderate scores (0.3–0.7) where heuristics are uncertain.

### Vulnerability Detection Heuristics

- **What:** Pattern-based detection of common binary vulnerability classes.
- **Where:** `security_modules/ai_assisted_binary_analysis/vulnerability_detection.py`
- **How:** `VulnerabilityDetector.detect_vulnerabilities(graph_store, func_addr)` scans instruction sequences in the PKG for:
  - **Unsafe calls:** `strcpy`, `gets`, `sprintf`, `scanf` without bounds checking
  - **Stack overflow patterns:** large local alloca + no stack cookie (`__stack_chk_fail` absent)
  - **Format string vulnerabilities:** `printf`-family with non-constant format argument
  - **Use-after-free indicators:** `free()` followed by pointer dereference in the same CFG path
  - **Integer overflow:** arithmetic before an array index or allocation size
    Results are tagged per-instruction with a severity level and stored as PKG annotations.

### Exploitability Analysis

- **What:** Scoring of how exploitable a detected vulnerability might be.
- **Where:** `security_modules/ai_assisted_binary_analysis/exploitability_analysis.py`
- **How:** `ExploitabilityAnalyzer.analyze(vulns)` takes a list of detected vulnerabilities and estimates exploitability by checking for the presence of mitigations (ASLR, stack canaries, NX bit) detected from binary headers, plus the exploitation difficulty of the specific vulnerability class. Returns a structured score with contributing factors.
