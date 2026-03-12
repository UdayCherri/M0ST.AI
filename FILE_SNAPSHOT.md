# M0ST Codebase Complete Snapshot

## Files Retrieved (All Full Contents)

### AI Security Agents (5 files)

1. **llm_agent.py** — LLM-based reasoning for RE tasks (OpenAI, Anthropic, Mistral, local)
   - Methods: infer_function_name, infer_variables, infer_types, summarize_function, etc.
   - Supports JSON output, tool calling, context-aware prompting with PKG embeddings

2. **static_agent.py** — Static binary analysis via radare2
   - Creates functions, basic blocks, instructions, flow edges in graph store
   - Handles Windows/Unix radare2 path resolution
   - Publishes STATIC_ANALYSIS_COMPLETE event

3. **pseudocode_agent.py** — Decompilation via Ghidra/radare2
   - Methods: decompile_function, decompile_all, clear_cache
   - Supports Ghidra headless, r2 pdg/pdc, and reconstruction from CFG

4. **dynamic_agent.py** — GDB-based runtime tracing
   - Traces execution on Linux, records register states and syscalls
   - Creates Run, ExecutesEdge, RuntimeFlow, SyscallEvent nodes
   - Not supported on Windows

5. **llm_semantic_agent.py** — AI-powered semantic analysis
   - Replaces heuristics with LLM+GNN embeddings for naming/typing/summarization
   - Fallback to classical methods when LLM unavailable
   - Full_analysis method combines all inference methods

### Knowledge Layer (3 files)

6. **knowledge/program_graph/**init**.py** — Program Knowledge Graph (PKG)
   - Central unified representation (Functions, BasicBlocks, Instructions, Variables, Structs, etc.)
   - Node types: FUNCTION, BASIC_BLOCK, INSTRUCTION, VARIABLE, STRUCT, STRING, IMPORT
   - Edge types: CALL, CFG_FLOW, DATA_FLOW, TYPE_RELATION, USES_STRING, IMPORTS, TYPE_OF
   - Backward compat with MemoryGraphStore API

7. **knowledge/embeddings/**init**.py** — EmbeddingStore
   - In-memory vector storage with cosine similarity search
   - Methods: store, get, search_similar, list_keys

8. **knowledge/symbol_database/**init**.py** — SymbolDatabase
   - Stores recovered function/variable names with confidence scores
   - Methods: add_function_name, add_variable_name, add_type_info

### AI Engine (2 files)

9. **ai_engine/symbol_recovery/**init**.py** — SymbolRecoveryEngine
   - Multi-stage name prediction: heuristics → embeddings → LLM
   - Variable name recovery, argument type inference, struct layout recovery
   - Persists to SymbolDatabase

10. **ai_engine/embedding_models/**init**.py** — BinaryEmbeddingEngine
    - GNN-based CFG embedding (GAT architecture)
    - Opcode feature vocabulary with 12 categories
    - Node features: opcode histogram + structural features
    - Fallback averaging if GNN unavailable, finds similar functions

### UI & Orchestration (4 files)

11. **ui/cli.py** — REPL CLI for M0ST
    - Commands: load, list funcs, info, blocks, insns, edges, explain, pseudocode, verify, trace, complexity, export, plugins, snapshot, status, config
    - AI commands: ai name, ai explain, ai types, ai refine, ai full, ai vulns, ai annotate, ai ask
    - Graph intelligence: find callers/callees, show callgraph/dataflow, similar

12. **orchestration/master_agent.py** — Top-level orchestrator
    - Initializes all agents (static, dynamic, GNN, LLM, pseudocode, semantic, verifier, Z3)
    - Legacy run_pipeline: static → heuristics → verify → GNN → dynamic → plugins → semantic → snapshot
    - AI-driven run_ai_pipeline via PlannerAgent
    - Registers LLM tools for agent coordination

13. **orchestration/planner_agent.py** — Multi-step planner
    - AnalysisResult dataclass for final output
    - 13-stage pipeline: static → call_graph → symbol_recovery → gnn → pseudocode → llm → verify → dynamic → z3 → plugins → refinement → snapshot
    - Single-function analysis methods: analyse_function, ai_name, ai_explain, ai_types, ai_refine, ai_ask, find_similar
    - Decision helpers: \_should_run_dynamic, \_should_run_z3

### Security Modules (3 files)

14. **security_modules/reverse_engineering/**init**.py** — Module marker
    - Restricted to program reconstruction only (CFG, call graph, pseudocode, etc.)
    - Security analysis lives in ai_assisted_binary_analysis

15. **security_modules/reverse_engineering/deobfuscation/**init**.py** — DeobfuscationEngine
    - Detects: control-flow flattening, opaque predicates, junk code, packers, virtualization
    - Methods: analyze, simplify
    - Computes obfuscation complexity score (0.0-1.0)

16. **security_modules/ai_assisted_binary_analysis/**init**.py** — Module marker
    - Handles security intelligence: vulnerability detection, exploitability, malware classification, unsafe patterns

### Data & Plugins (2 files)

17. **plugins/**init**.py** — PluginManager
    - Dynamic recursive plugin discovery from plugins/ directory
    - Plugin interface: analyze(graph_store, func_addr) → dict
    - Routes results through PKG annotations when available

18. **data/datasets/**init**.py** — Dataset pipeline
    - DatasetPipeline: collects 4 dataset types (embeddings, vulnerabilities, symbols, deobfuscation)
    - SourceCompiler: compiles C/C++ with/without debug info for training data
    - TrainingDataGenerator: pairs debug/stripped binaries, extracts ground-truth labels

### Core (1 file)

19. **core/capabilities.py** — Capability-based access control
    - Enum: STATIC_READ, STATIC_WRITE, DYNAMIC_EXECUTE, SEMANTIC_REASON, VERIFY, SNAPSHOT, PLUGIN_ANALYSIS, LLM_INFERENCE, GNN_INFERENCE, PSEUDOCODE, PLANNING
    - enforce_capability(agent, capability) function

## Key Insights

- **PKG (Program Knowledge Graph)** is the central hub for all inter-agent communication
- **LLMSemanticAgent** replaces heuristics with LLM+GNN for AI-driven analysis
- **PlannerAgent** orchestrates 13-stage pipeline with conditional stages (dynamic, z3)
- **Capabilities system** prevents unauthorized operations across agents
- **Plugin system** allows extensible analysis via PKG annotations
- **Dataset pipeline** supports fine-tuning GNN/LLM with labeled training data
- **CLI** provides both legacy (show, load) and AI (ai name, ai explain) command sets
