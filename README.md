# M0ST — AI Security System

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: Research](https://img.shields.io/badge/license-research-lightgrey.svg)]()
[![Platform: Linux/Windows](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-informational.svg)]()

**M0ST** is a research-grade modular platform for building AI-powered security tools. It is not a single tool — it is an ecosystem of security modules and AI agents designed to assist analysts with a broad range of security tasks.

M0ST provides a layered architecture where each module can be used independently or composed into investigation pipelines. The platform combines classical analysis techniques with modern AI capabilities including LLM reasoning, graph neural networks, and embedding models.

> **Status:** M0ST is an evolving research platform under active development. The **AI Reverse Engineering** module is fully functional. Additional security modules are planned and described in the roadmap below.

---

## Vision and Goals

The long-term vision for M0ST is to provide a unified platform where security analysts can:

- Investigate binaries, malware, network captures, and threat intelligence using AI-assisted tools
- Compose modular analysis pipelines that combine multiple security disciplines
- Leverage AI agents that autonomously coordinate modules and reason about results
- Build and share reusable security modules within a common architecture

Target domains include:

- **Reverse engineering** — automated binary analysis, function recovery, decompilation
- **Binary analysis** — vulnerability detection, malware classification, risk scoring
- **Malware analysis** — behavioral analysis, indicator extraction, family classification
- **Network traffic analysis** — PCAP inspection, protocol analysis, anomaly detection
- **Reconnaissance** — attack surface mapping, asset discovery
- **Threat intelligence** — indicator correlation, threat graph construction
- **Incident investigation** — evidence collection, timeline reconstruction

---

## 7-Layer Architecture

M0ST is built on a 7-layer architecture. Each layer has a distinct responsibility and communicates with adjacent layers through well-defined interfaces.

### 1. Interface Layer

The entry points through which users and external systems interact with M0ST.

- **CLI** — interactive command-line interface for analysis workflows
- **Web Dashboard** — browser-based interface (planned)
- **APIs** — programmatic access for integration with other tools (planned)

### 2. AI Security Agents Layer

Autonomous investigation agents that coordinate modules and reason about analysis results. Agents receive tasks from the orchestration layer, invoke the appropriate security modules, and synthesize findings into actionable intelligence.

### 3. Orchestration Layer

Manages workflow execution, task scheduling, and module pipelines. The orchestration layer decides which agents and modules to invoke for a given investigation, sequences their execution, and aggregates results.

### 4. Security Modules Layer

Modular, self-contained tools that perform specific security analysis tasks. Each module exposes a consistent interface and can operate independently or as part of a larger pipeline.

Example modules (planned and in-progress):

| Module                          | Description                                                      |
| ------------------------------- | ---------------------------------------------------------------- |
| AI Reverse Engineering          | Binary disassembly, CFG recovery, symbol recovery, decompilation |
| AI Binary Intelligence          | Vulnerability detection, malware classification, risk scoring    |
| AI Malware Analysis             | Behavioral analysis, indicator extraction, family clustering     |
| Dynamic Analysis Sandbox        | Instrumented execution and runtime observation                   |
| PCAP / Network Traffic Analysis | Protocol parsing, traffic classification, anomaly detection      |
| AI Reconnaissance               | Attack surface discovery and asset enumeration                   |
| Threat Intelligence Correlation | Indicator matching, threat graph enrichment                      |

### 5. AI Engine Layer

The AI models and inference infrastructure shared across all security modules.

- **LLM Reasoning** — multi-provider LLM integration (OpenAI, Anthropic, Mistral, local/Ollama) for semantic analysis, code explanation, and natural language generation
- **ML Detection Models** — trained classifiers for vulnerability patterns, malware families, and anomaly detection
- **Graph Models** — GNN architectures (GAT, GraphSAGE, GINE) for structural reasoning over control-flow graphs and knowledge graphs
- **Embedding Models** — vector representations of code, binaries, and threat indicators for similarity search

### 6. Knowledge Layer

Structured intelligence extracted from analysis, stored for querying and cross-referencing.

- **Threat Knowledge Graph** — relationships between functions, indicators, vulnerabilities, and threat actors
- **Vector Embeddings** — searchable embedding store for similarity-based retrieval
- **Intelligence Database** — persisted analysis results, symbol mappings, and metadata

### 7. Data Layer

Raw evidence storage for all input data consumed by the platform.

- **Binaries** — executable samples and firmware images
- **PCAPs** — network packet captures
- **Logs** — system, application, and security logs
- **Telemetry** — endpoint and network telemetry data
- **Datasets** — training and evaluation data for AI models

---

## Security Modules Concept

Each security module in M0ST is a self-contained analysis unit that:

- Operates on data from the Data Layer
- Uses AI Engine capabilities as needed
- Produces structured results stored in the Knowledge Layer
- Can be invoked independently via the CLI/API or composed into pipelines by the Orchestration Layer

This modular design means new security capabilities can be added without modifying the core platform. Modules share the same AI infrastructure, storage backends, and orchestration framework.

---

## Current Development Status

M0ST is in active research development. The platform architecture is established and the first module is fully functional.

### What exists today

- **Platform architecture** — 7-layer structure with core infrastructure for configuration, capabilities, events, and intermediate representation
- **AI Reverse Engineering module** — binary disassembly via radare2, CFG extraction, pseudocode extraction (Ghidra/radare2), vulnerability detection, malware classification
- **11 AI agents** — static analysis, GNN graph analysis, LLM inference, pseudocode, dynamic tracing, verification, constraint solving, semantic reasoning, heuristic pattern matching, LLM-semantic pipeline, CFG post-processing
- **Orchestration** — pipeline controller (`MasterAgent`) and 13-stage intelligent planner (`PlannerAgent`) for coordinating agents
- **AI Engine** — GNN models (GAT, GraphSAGE, GINE), multi-provider LLM integration (OpenAI / Anthropic / Mistral / Ollama), symbol recovery pipeline (3-stage: heuristic → embedding → LLM)
- **Program Knowledge Graph (PKG)** — unified in-memory graph IR with 8 node types and 8 edge types; single source of truth for all analysis results
- **Storage** — in-memory graph store, SQLite persistence, snapshot/versioning system
- **Plugin system** — dynamic plugin loading with 5 built-in plugins: anti-debug detection, crypto detection, entropy analysis, magic-byte pattern detection, string decoding
- **Interactive CLI** — module selection menu, paginated help, verbose/quiet mode, tab-completion, fuzzy command suggestions, Braille spinner for long operations
- **Security modules** — vulnerability detection (unsafe calls, stack overflow, format strings, UAF, integer overflow), malware risk scoring, exploitability analysis, unsafe pattern detection
- **Analysis utilities** — cyclomatic complexity, JSON export, constraint solving, CFG cleanup
- **Docker support** — containerised deployment

### What is not yet implemented

- Web dashboard
- REST API
- Security modules beyond reverse engineering (malware analysis, network analysis, reconnaissance, threat intelligence)
- Knowledge layer services (unified vector store, threat knowledge graph, cross-module intelligence DB)

---

## Novelty and Key Innovations

M0ST introduces several novel contributions to the field of AI-assisted security analysis:

### 1. Minimal-Feature Triplet Embedding Architecture

**Innovation:** Training CFG embeddings on abstract, architecture-independent 4-dimensional features via triplet loss, achieving 95% margin accuracy on cross-architecture functions.

- **Why Novel:** Prior work relied on complex hand-crafted features (18–50 dimensions) or end-to-end opcode embeddings (sensitive to disassembly variants). M0ST shows that minimal features capture sufficient structural variation while ensuring robustness across architectures, compilers, and obfuscation.
- **Impact:** 10× faster training, 78% reduction in feature engineering overhead, improved cross-architecture generalization
- **Details:** See [BENCHMARKS_AND_LIMITATIONS.md](BENCHMARKS_AND_LIMITATIONS.md) and [LITERATURE_REVIEW.md](LITERATURE_REVIEW.md)

### 2. Modular Multi-Agent Architecture with Shared Knowledge Graph

**Innovation:** Unified framework where specialized security agents (static, dynamic, symbolic, LLM-based) operate on a shared Program Knowledge Graph (PKG), with automatic task coordination via planner.

- **Why Novel:** Prior systems featured monolithic tools or disconnected analysis stages without cross-domain reasoning. M0ST provides a plug-and-play agent ecosystem where new analysis methods integrate without modifying core orchestration.
- **Impact:** Extensible research platform; fast prototyping of novel security analysis techniques; complex cross-domain queries
- **Details:** See [ARCHITECTURE.md](ARCHITECTURE.md) and [DESIGN_PRINCIPLES.md](DESIGN_PRINCIPLES.md)

### 3. Dynamic Agent Specialization Based on Binary Properties

**Innovation:** Runtime agent instantiation based on detected binary properties (architecture, packing status, language) rather than static configuration.

- **Why Novel:** Traditional approaches use pre-defined agent compositions. M0ST inspects binaries and automatically selects the optimal agent mix.
- **Impact:** Adaptive workflows that respond to binary characteristics; reduced manual configuration
- **Details:** See `DynamicAgent` in [ai_security_agents/dynamic_agent.py](ai_security_agents/dynamic_agent.py)

### 4. Knowledge Graph as Unified Analysis State

**Innovation:** Single PKG entity model serves as cross-cutting state shared by all agents, enabling reasoning across static/dynamic/symbolic domains without data export/import.

- **Why Novel:** Each traditional tool maintains separate state; coordination requires manual data transfer. M0ST's PKG is the "single source of truth" for program entities.
- **Impact:** Enables complex cross-domain queries (e.g., "functions executed in this trace that contain these vulnerability patterns")
- **Details:** See [core/ir.py](core/ir.py) and [knowledge/program_graph/](knowledge/program_graph/)

### 5. Hierarchical Multi-Stage Symbol Recovery

**Innovation:** Three-stage symbol recovery pipeline combining heuristic-based detection, embedding-based similarity, and LLM-based semantic inference.

- **Why Novel:** Simple heuristics miss symbols; embeddings are fast but lack semantic grounding. M0ST combines all three for robust recovery.
- **Impact:** Higher symbol recovery rates on stripped binaries
- **Details:** See [security_modules/reverse_engineering/symbol_recovery/](security_modules/reverse_engineering/symbol_recovery/)

---

## Research References

**Key Papers Referenced:** FaceNet (triplet loss), GraphSAGE, Graph Attention Networks (GAT), GNN expressiveness theory, and program analysis classics. See [LITERATURE_REVIEW.md](LITERATURE_REVIEW.md) for detailed citations and research foundations.

**Performance Validation:** M0ST's triplet encoder validated on 10,000 test triplets with 95.06% margin accuracy. See [BENCHMARKS_AND_LIMITATIONS.md](BENCHMARKS_AND_LIMITATIONS.md) for full evaluation protocols and limitations.

---

## Planned Modules

The following modules are on the research roadmap. They are not yet implemented.

| Module                          | Description                                                                |
| ------------------------------- | -------------------------------------------------------------------------- |
| AI Malware Analysis             | Automated behavioral analysis, family classification, indicator extraction |
| Dynamic Analysis Sandbox        | Instrumented execution environments for runtime analysis                   |
| PCAP / Network Traffic Analysis | Deep packet inspection, protocol analysis, traffic anomaly detection       |
| AI Reconnaissance               | Automated attack surface mapping and asset discovery                       |
| Threat Intelligence Correlation | Cross-referencing indicators across analysis results and external feeds    |

---

## Repository Structure

```
├── main.py                         # Entry point
├── config.yml                      # Configuration (LLM, GNN, tools)
│
├── interface/                      # Layer 1: Interface
│   ├── cli/                        #   CLI entry point
│   ├── api/                        #   API server (planned)
│   └── commands/                   #   Command handlers
│
├── ai_security_agents/             # Layer 2: AI Security Agents
│   ├── static_agent.py             #   radare2 disassembly
│   ├── graph_agent.py              #   GNN structural analysis
│   ├── llm_agent.py                #   Multi-provider LLM wrapper
│   ├── pseudocode_agent.py         #   Ghidra/r2 decompilation
│   ├── llm_semantic_agent.py       #   AI-powered semantic reasoning
│   ├── dynamic_agent.py            #   GDB-based dynamic tracing
│   ├── verifier_agent.py           #   Verification and unsafe patterns
│   ├── z3_agent.py                 #   Constraint solving
│   ├── semantic_agent.py           #   Rule-based explanation
│   ├── heuristics_agent.py         #   Classical pattern matching
│   └── static_post.py              #   CFG cleanup
│
├── orchestration/                  # Layer 3: Orchestration
│   ├── master_agent.py             #   Pipeline controller
│   └── planner_agent.py            #   Multi-stage planner
│
├── security_modules/               # Layer 4: Security Modules
│   ├── reverse_engineering/        #   Disassembly, CFG, deobfuscation
│   └── ai_assisted_binary_analysis/#   Vulnerability + malware detection
│
├── ai_engine/                      # Layer 5: AI Engine
│   ├── gnn_models/                 #   GAT, GraphSAGE, GINE
│   ├── embedding_models/           #   Binary embedding pipeline
│   ├── llm_inference/              #   Multi-provider LLM wrapper
│   ├── symbol_recovery/            #   Function/variable name recovery
│   └── training/                   #   Model training utilities
│
├── knowledge/                      # Layer 6: Knowledge (in progress)
│   ├── program_graph/              #   Analysis graph store
│   ├── embeddings/                 #   Embedding store
│   ├── symbol_database/            #   Recovered symbol store
│   └── semantic_index/             #   Semantic metadata index
│
├── data/                           # Layer 7: Data
│   ├── binaries/                   #   Binary samples
│   ├── analysis_results/           #   Persisted outputs
│   └── datasets/                   #   Training data
│
├── core/                           # Config, capabilities, events, IR
├── storage/                        # In-memory graph, SQLite, snapshots
├── plugins/                        # Extensible analysis plugins
├── analysis/                       # Complexity, export, constraints
├── ui/                             # CLI implementation
├── docker/                         # Docker deployment
└── tests/                          # Unit tests and test binaries
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- Optional: [radare2](https://github.com/radareorg/radare2) (core disassembly engine — strongly recommended)
- Optional: [Ghidra](https://ghidra-sre.org/) (pseudocode / decompilation)
- Optional: GDB (Linux only, for dynamic tracing)
- Optional: OpenAI / Anthropic / Ollama API key (for LLM features)

### Installation

```bash
# Clone the repository
git clone https://github.com/CYB3R-BO1/M0ST.git
cd M0ST

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate      # Linux / macOS
# .venv\Scripts\activate.bat   # Windows cmd
# .\.venv\Scripts\Activate.ps1 # Windows PowerShell

# Install dependencies
pip install -r requirements.txt

# Copy and edit configuration
cp config.yml.example config.yml   # Linux
# copy config.yml.example config.yml   # Windows
# Edit config.yml with your tool paths and API keys
```

### Running M0ST

```bash
# Launch the interactive CLI
python main.py

# Load a binary directly on startup
python main.py path/to/binary

# Launch with verbose output enabled
python main.py --verbose
```

### CLI Quick Start

On first launch, M0ST shows a **module selection menu**:

```
  Select analysis modules to enable:
    [1] Reverse Engineering
    [2] AI Binary Intelligence
    [3] Network Traffic Analysis
    [0] Full Mode (all modules)

  Enter choice (default: 0 — Full Mode):
```

Once inside the REPL:

```
m0st> load tests/binaries/ret          # Load a binary and run the pipeline
m0st> list funcs                        # Show all discovered functions
m0st> info 0x401000                     # Function details
m0st> blocks 0x401000                   # Basic blocks in a function
m0st> insns 0x401000                    # Disassembly listing
m0st> complexity                        # Cyclomatic complexity for all functions
m0st> pseudocode 0x401000              # Decompile a function
m0st> ai name 0x401000                 # LLM-suggested function name
m0st> ai explain 0x401000              # LLM-generated function summary
m0st> ai ask what does this binary do? # Free-form AI analyst query
m0st> ai vulns 0x401000                # Vulnerability analysis for a function
m0st> plugins list                      # List all loaded plugins
m0st> plugins run 0x401000             # Run all plugins on a function
m0st> find callers 0x401000            # Find all call sites
m0st> callgraph                         # Visualise inter-procedural call graph
m0st> snapshot save my_snapshot        # Save current analysis state
m0st> export report.json               # Export full analysis to JSON
m0st> status                           # Tool and capability status
m0st> verbose on                        # Enable verbose pipeline output
m0st> verbose off                       # Quiet mode (spinner only)
m0st> help                              # Paginated help index
m0st> help ai                           # AI command help page
m0st> help graph                        # Graph command help page
m0st> quit
```

### Docker

```bash
cd docker
docker compose up -d
docker compose exec m0st python main.py
```

See [SETUP.md](SETUP.md) for full installation instructions, optional AI/ML dependencies, and troubleshooting.

---

## Future Research Directions

- **Additional security modules** — malware analysis, network traffic analysis, reconnaissance, threat intelligence correlation
- **Web dashboard** — browser-based investigation interface
- **REST API** — programmatic access for CI/CD integration and external tooling
- **Threat knowledge graph** — unified graph database linking findings across all modules
- **Collaborative analysis** — multi-analyst workflows with shared state
- **Model training pipelines** — fine-tuning GNN and LLM models on domain-specific security datasets
- **Plugin ecosystem** — community-contributed analysis plugins

---

## Documentation

| Document                                     | Description                                                                  |
| -------------------------------------------- | ---------------------------------------------------------------------------- |
| [SETUP.md](SETUP.md)                         | Installation guide (Linux + Windows), optional dependencies, troubleshooting |
| [ARCHITECTURE.md](ARCHITECTURE.md)           | System design, data flow diagrams, layer breakdown                           |
| [TECHNOLOGIES.md](TECHNOLOGIES.md)           | All technologies and concepts used — what, where, and how                    |
| [LITERATURE_REVIEW.md](LITERATURE_REVIEW.md) | Literature survey, research gaps, and M0ST's methodology                     |
| [PLUGINS.md](PLUGINS.md)                     | Plugin development guide and API reference                                   |
| [DESIGN_PRINCIPLES.md](DESIGN_PRINCIPLES.md) | Guiding design decisions                                                     |

---

## License

Research use. See repository for license details.
