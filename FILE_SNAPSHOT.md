# M0ST Codebase Snapshot

Updated: 2026-03-16

## Project Identity

M0ST is an AI Security System platform with a 7-layer architecture. Reverse engineering and binary analysis are implemented modules inside the Security Modules layer, not the full scope of the platform.

## Verified Inventory (Current Workspace)

### 1. AI Security Agents Layer

Path: ai_security_agents/

- 11 agent implementations plus package export file.
- Agent files:
  - **static_agent.py**: Runs static binary analysis and populates functions, basic blocks, instructions, and CFG links.
  - **graph_agent.py**: Builds graph-derived structural features and embeddings for downstream reasoning.
  - **llm_agent.py**: Provides provider-agnostic LLM inference and structured JSON response handling.
  - **pseudocode_agent.py**: Generates pseudocode using configured decompilation backends.
  - dynamic_agent.py: Executes runtime tracing with strategy-based backends (gdb/docker/windbg/x64dbg).
  - verifier_agent.py: Validates graph consistency and reports suspicious or contradictory edges.
  - semantic_agent.py: Produces rule-based semantic interpretations and explanations.
  - z3_agent.py: Performs SMT-backed constraint reasoning and feasibility checks.
  - heuristics_agent.py: Applies classical heuristics for quick pattern and behavior signals.
  - static_post.py: Cleans and normalizes static-analysis artifacts after extraction.
  - llm_semantic_agent.py: Combines PKG context with LLM reasoning for high-level semantic outputs.
- Package export: **init**.py: Re-exports agent classes for layer-level imports.

Key note:

- Dynamic analysis is strategy-based, with support for gdb, docker, windbg, and x64dbg backends.

### 2. Orchestration Layer

Path: orchestration/

- master_agent.py: Initializes system components and runs legacy or AI-driven orchestration flows.
- planner_agent.py: Executes staged planning pipeline and aggregates run results in AnalysisResult.
- **init**.py: Defines orchestration package boundary and layer identity.

### 3. Security Modules Layer

Path: security_modules/

- reverse_engineering/
  - **init**.py: Scopes reverse-engineering module purpose to program reconstruction.
  - disassembly/**init**.py: Exposes disassembly helpers and normalized instruction retrieval.
  - cfg_recovery/**init**.py: Builds control-flow graph structures from analyzed code.
  - function_boundary/**init**.py: Detects function boundaries and entry/exit candidates.
  - call_graph/**init**.py: Builds inter-procedural call relationships.
  - pseudocode/**init**.py: Provides pseudocode-level reconstruction interfaces.
  - type_inference/**init**.py: Infers probable type information from program evidence.
  - struct_recovery/**init**.py: Recovers struct layouts and field usage relations.
  - semantic_labeling/**init**.py: Assigns semantic labels to reconstructed program units.
  - deobfuscation/**init**.py: Detects and simplifies obfuscation patterns.
- ai_assisted_binary_analysis/
  - **init**.py: Marks AI-assisted security-intelligence module scope.
  - vulnerability_detection.py: Detects vulnerability patterns and reports severity-tagged findings.
  - malware_classification.py: Computes suspicious behavior scores and risk classifications.
  - exploitability_analysis.py: Estimates exploitability with mitigation-aware adjustments.
  - unsafe_pattern_detection.py: Flags insecure coding and unsafe security anti-patterns.
- security_modules/**init**.py: Layer package marker and module grouping boundary.

### 4. AI Engine Layer

Path: ai_engine/

- **gnn_models/**init**.py**: Defines graph model wrappers used in structural learning workflows.
- **embedding_models/**init**.py**: Generates and compares embeddings for similarity and context.
- **llm_inference/**init**.py**: Shared LLM inference abstraction for engine-level integrations.
- **symbol_recovery/**init**.py**: Recovers symbols using heuristic, embedding, and LLM stages.
- **training/**init**.py**: Training-related helpers and model lifecycle utilities.
- **ai_engine/**init**.py**: Package export for AI engine components.

### 5. Knowledge Layer

Path: knowledge/

- program_graph/**init**.py: Implements PKG entities/relations and graph operations.
- embeddings/**init**.py: Stores vectors and serves similarity search queries.
- symbol_database/**init**.py: Persists symbol candidates with confidence/source metadata.
- semantic_index/**init**.py: Maintains semantic indexing helpers for retrieval.
- knowledge/**init**.py: Package export for knowledge-layer components.

### 6. Storage and Analysis Utilities

Paths:

- storage/
  - memory_graph_store.py: In-memory store for graph facts during active analysis.
  - sqlite_store.py: Durable storage for metadata and selected analysis outputs.
  - snapshots.py: Creates and restores reproducible analysis snapshots.
  - schema.cypher: Graph schema reference for relationship modeling.
- analysis/
  - complexity.py: Computes cyclomatic complexity and classifies control-flow complexity.
  - constraint_pass.py: Applies constraint-guided pruning of infeasible control-flow paths.
  - export.py: Exports analysis state and summaries to JSON.

### 7. Plugin System

Path: plugins/

- plugin manager:
  - **init**.py: Recursively discovers, loads, and executes plugin analyzers.
- currently present plugin modules:
  - anti_debug/anti_debug.py: Detects anti-debugging behavior signatures.
  - crypto/crypto_detect.py: Detects suspicious crypto constants and API usage.
  - entropy/entropy_analysis.py: Produces entropy-based packed/encoded code signals.
  - loop_detect/loop_detect.py: Flags loop-heavy instruction behaviors.
  - magic_pattern/magic_detect.py: Matches magic bytes and known marker patterns.
  - network_api/network_api.py: Flags suspicious network API usage.
  - packer_detect/packer_detect.py: Detects indicators of packers/protectors.
  - string_decoder/string_decode.py: Detects probable string decoding logic.
  - string_decrypt/string_decrypt.py: Detects probable string decryption routines.

### 8. Interface and Entry Points

Paths:

- main.py: Bootstraps the application and launches the interface entrypoint.
- ui/cli.py: Main interactive CLI and command orchestration surface.
- interface/cli/**init**.py: CLI package bridge for interface layer imports.
- interface/api/**init**.py: API package scaffold for service endpoints.
- interface/commands/**init**.py: Command-handler package scaffold.

### 9. Data and Training Pipeline

Paths:

- data/datasets/**init**.py: Dataset collection and training-data generation utilities.
- data/binaries/**init**.py: Binary repository package marker and related hooks.
- data/analysis_results/**init**.py: Analysis-result package marker and persistence hooks.
- data/**init**.py: Data-layer package marker and shared data-layer entry.

Highlights:

- DatasetPipeline supports function_embeddings, vulnerability_labels, symbol_recovery, and deobfuscation datasets.
- Includes source compilation and stripped/debug pairing for training data generation.

## Current Pipeline Snapshot

### Legacy Pipeline (MasterAgent)

static -> heuristics -> verify -> gnn -> dynamic -> plugins -> semantic -> snapshot

### AI-Driven Pipeline (PlannerAgent)

static_analysis -> call_graph_building -> symbol_recovery -> gnn_analysis -> pseudocode_extraction -> llm_analysis -> verification -> dynamic_analysis (conditional) -> z3_analysis (conditional) -> plugin_analysis -> refinement -> snapshot

