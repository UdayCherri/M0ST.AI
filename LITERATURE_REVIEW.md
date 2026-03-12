# M0ST — Literature Review, Research Gaps, and Methodology

**Course:** Mini Project — First Review  
**Evaluation Criteria:** Literature Survey (10) · Methodology/Novelty (10) · Presentation (10) · Guide Interaction (10)

---

## Table of Contents

1. [Introduction and Problem Statement](#1-introduction-and-problem-statement)
2. [Literature Survey](#2-literature-survey)
   - 2.1 Traditional Static Analysis Tools
   - 2.2 Machine-Learning Approaches to Binary Analysis
   - 2.3 Graph Neural Networks for Binary Code
   - 2.4 Large Language Models for Code Understanding
   - 2.5 Dynamic Analysis and Symbolic Execution
   - 2.6 Hybrid and Multi-Agent Security Systems
3. [Comparative Analysis](#3-comparative-analysis)
4. [Research Gaps Identified](#4-research-gaps-identified)
5. [Proposed Methodology](#5-proposed-methodology)
6. [Novelty of M0ST](#6-novelty-of-most)
7. [Experimentation Plan](#7-experimentation-plan)
8. [References](#8-references)

---

## 1. Introduction and Problem Statement

### Background

Binary analysis is the process of examining compiled executable programs without access to their source code. It is a core discipline in:

- **Vulnerability research** — finding exploitable flaws in closed-source software
- **Malware analysis** — understanding the behaviour of hostile programs
- **Reverse engineering** — reconstructing program logic for interoperability or security auditing
- **Incident response** — determining what an attacker's tool did to a system

The challenge is fundamental: compilers discard human intent. Variable names, function names, type information, comments, and high-level structure are stripped away at compile time. What remains is a flat sequence of machine instructions that represents the same logic but with all semantic context removed.

A human analyst reversing a stripped binary must manually reconstruct:

1. What each function does (semantic understanding)
2. How functions relate to each other (structural understanding)
3. Which functions present security risks (security reasoning)

This process is time-consuming, error-prone, and does not scale. A typical malware sample contains hundreds to thousands of functions. A firmware image may contain tens of thousands. Manual analysis of even a single sample can take days or weeks.

### Research Motivation

The field has responded with three waves of automation:

1. **Tool-based automation** (1990s–2010s): Interactive disassemblers (IDA Pro, Ghidra), debuggers (OllyDbg, x64dbg), and scripting APIs that accelerate individual analyst tasks — but still require expert human guidance at every step.

2. **Machine-learning automation** (2015–2022): Statistical models trained on large binary corpora to automate specific sub-tasks — function similarity search, vulnerability detection, malware classification. These work well on the narrow tasks they were trained for but are brittle outside their training distribution.

3. **LLM and GNN integration** (2022–present): Large language models bring broad semantic reasoning; graph neural networks bring structural reasoning over code graphs. The combination potentially enables a new level of automated understanding — but so far these have been applied in isolation, as single-task tools, rather than as components of an integrated analysis platform.

M0ST's research objective is to investigate how these three generations of techniques can be unified into a coherent, modular, extensible platform that supports the full analysis workflow.

---

## 2. Literature Survey

### 2.1 Traditional Static Analysis Tools

#### IDA Pro (Hex-Rays, 1990–present)

IDA Pro is the industry-standard interactive disassembler and decompiler. Its Hex-Rays decompiler produces C-like pseudocode from x86/ARM/MIPS binaries. IDA exposes a Python scripting API (IDAPython) that allows automation of repetitive tasks. Despite decades of development, IDA remains fundamentally interactive — it presents information to a human analyst who must interpret it. IDA Pro is proprietary and costs several thousand dollars per seat.

**Limitation:** Requires expert human interpretation; no AI-assisted reasoning; proprietary and costly; not composable into automated pipelines.

#### Ghidra (NSA, 2019)

Ghidra is NSA's open-source alternative to IDA Pro. Its decompiler (`analyzeHeadless`) can be invoked non-interactively, making it suitable for automated pipelines. Quality of decompilation is competitive with Hex-Rays. Ghidra's script API (Java/Python) allows custom analysis extension.

M0ST integrates Ghidra as an optional decompilation backend in `PseudocodeAgent`. When configured, Ghidra's output provides significantly higher-quality pseudocode than radare2's built-in decompiler.

**Limitation:** Decompilation without semantic understanding — output is C-like code that still requires expert interpretation; no machine learning integration in core Ghidra.

#### radare2 (radare.org, 2006–present)

radare2 is a portable, open-source reverse engineering framework. Its strengths are programmatic access (via `r2pipe`), cross-platform support, and a rich command set. radare2's built-in analysis (`aaa`) performs function boundary detection, CFG extraction, cross-reference analysis, and string identification.

M0ST uses radare2 as its primary disassembly engine through `r2pipe`. Every function's CFG, instruction listing, and xrefs are extracted from radare2 and stored in the PKG.

**Limitation:** Limited semantic analysis; no ML integration; command-line workflow not suited for automated multi-stage pipelines.

#### Binary Ninja (Vector35, 2016–present)

Binary Ninja offers a modern, scriptable RE platform with a clean intermediate representation (BNIL). Its HLIL layer produces clean high-level code. Its Python API is particularly clean for building automated analysis tools.

**Limitation:** Proprietary; no native ML integration; not composable with LLM/GNN pipelines out of the box.

#### angr (UC Santa Barbara, 2016)

angr is a Python-based binary analysis platform that combines static analysis with dynamic symbolic execution. It can automatically reason about program paths, discover vulnerabilities, and generate inputs that trigger specific code paths. angr is widely used in academic binary analysis research.

**Limitation:** Does not scale to large, real-world binaries with complex control flow; symbolic execution state explosion is a fundamental limitation; no LLM integration.

---

### 2.2 Machine-Learning Approaches to Binary Analysis

#### Genius — Graph Embedding for Binary Code Similarity (Feng et al., 2016)

Genius introduced the idea of representing functions as Attributed Control-Flow Graphs (ACFGs) and using a graph embedding to measure cross-architecture binary similarity. ACFGs annotate basic blocks with statistical features (instruction counts, string counts, call counts, arithmetic ratios, etc.).

**Key contribution:** First system to use graph-level embedding for binary similarity.

**Limitation:** Hand-crafted features; not learned end-to-end; requires pre-built codebook; does not generalise to semantic similarity.

**M0ST relation:** M0ST uses learnable GNN embeddings over the same ACFG representation, eliminating the need for a hand-crafted codebook.

#### GEMINI — Neural Networkable Binary Code Similarity Detection (Xu et al., 2017, S&P)

GEMINI uses a two-phase approach: Structure2Vec (a message-passing GNN) to embed ACFGs into vectors, then a Siamese neural network to measure pairwise similarity. Trained on binary functions with known ground truth, GEMINI can find similar functions across compilers and architectures.

**Key contribution:** End-to-end trainable GNN for binary similarity; Siamese architecture for pairwise comparison.

**Limitation:** Requires pre-labelled training data; only addresses function similarity, not semantic understanding; no integration with symbolic or LLM reasoning.

**M0ST relation:** M0ST's `GraphAgent` builds on this idea (GNN over CFG) but extends it to support multiple GNN architectures (GAT, GraphSAGE, GINE) and integrates the embedding into a broader analysis pipeline rather than using it for similarity only.

#### Asm2Vec (Ding et al., 2019, S&P)

Asm2Vec applies the Word2Vec neural language model directly to assembly instruction sequences. It learns vector representations of instructions and functions from a large corpus of assembly code, enabling semantic similarity search without CFG structure.

**Key contribution:** Language-model approach to assembly code; captures syntactic patterns in instruction sequences.

**Limitation:** Ignores control-flow structure; sequence models can't capture non-local dependencies in complex functions; no semantic understanding of what the code does.

#### Punstrip / EKLAVYA (Chua et al., 2017)

Uses neural networks to recover function type signatures (argument types, return types) from stripped binaries. Learns type recovery as a sequence labelling task over the instruction sequence.

**M0ST relation:** M0ST's `LLMAgent` addresses type inference with LLM reasoning over the combined evidence of disassembly + pseudocode + GNN embedding, achieving richer type recovery than pure pattern matching.

#### PalmTree (Li et al., 2021)

PalmTree uses transformer-based pre-training on assembly code, learning context-aware instruction embeddings. Similar to BERT but for assembly. Achieved state-of-the-art results on binary similarity and function recovery benchmarks.

**Key contribution:** Self-supervised pre-training on assembly; instruction-level contextual embeddings.

**Limitation:** Still a similarity/matching system; does not produce semantic explanations; not integrable into interactive analysis workflows.

---

### 2.3 Graph Neural Networks for Binary Code

#### Multi-view Graph Neural Networks (Liu et al., 2020)

Uses multiple graph representations of the same function (CFG, DFG, call graph) as separate views, fusing their embeddings for richer function representation. Showed that combining structural views outperforms single-view approaches.

**M0ST relation:** M0ST's PKG captures all three views (CFG via `CFG_FLOW` edges, data flow via `DATA_FLOW` edges, calls via `CALL` edges) in a single unified graph. Multi-view fusion is a planned enhancement.

#### jTrans (Wang et al., 2022, CCS)

jTrans is a jump-aware transformer for binary code similarity. It explicitly models jump targets in the attention mechanism, capturing long-range control-flow dependencies that standard transformers miss.

**Key contribution:** First work to incorporate jump semantics into transformer-based binary analysis.

**M0ST relation:** M0ST's GAT with CFG structure achieves similar long-range dependency capture through the graph topology, rather than a custom attention mask.

#### BinaryAI (Jiang et al., 2023)

BinaryAI combines a transformer-based instruction encoder with a graph representation of the call graph to achieve cross-architecture function similarity. Demonstrated that call-graph context above the function level significantly improves matching accuracy.

**Key contribution:** Cross-architecture, call-graph-aware function matching.

**M0ST relation:** M0ST's `CALL` edge type in the PKG provides call graph information. Future work includes incorporating inter-procedural context into the GNN as described in BinaryAI.

---

### 2.4 Large Language Models for Code Understanding

#### GPT-4 Technical Report (OpenAI, 2023)

GPT-4 demonstrated surprising proficiency at code understanding tasks, including explaining assembly code, identifying bugs, and reasoning about security vulnerabilities. Early explorations showed that GPT-4 could provide meaningful function summaries from short disassembly listings.

**Limitation:** Works on short snippets only; loses coherence on long functions; "hallucination" — plausible but incorrect code explanations; no ground truth in the prompt.

**M0ST relation:** M0ST mitigates hallucination by grounding the LLM prompt with PKG facts: actual disassembly, pseudocode, import names, string literals, and GNN-based function comparisons. The LLM is instructed to reference only the provided data.

#### LLM4Decompile (Tan et al., 2024)

A fine-tuned LLM specifically for decompilation — translating assembly to C source code. Outperforms Ghidra on function recovery benchmarks for certain function classes. Uses a large dataset of compiler-generated assembly + source pairs for supervised fine-tuning.

**Key contribution:** First high-quality LLM-based decompiler.

**Limitation:** Requires fine-tuning on large supervised datasets; decompilation quality degrades on obfuscated or hand-crafted assembly.

**M0ST relation:** M0ST uses Ghidra/r2 for decompilation and LLM for semantic explanation rather than decompilation. LLM4Decompile-style output is a future direction for M0ST's `PseudocodeAgent`.

#### SLaDe (Armengol-Estapé et al., 2023)

SLaDe (Source-Language-Directed Decompilation) uses language models guided by the source language syntax to improve decompilation accuracy. Demonstrates that constrained generation produces more compilable, semantically accurate output.

**M0ST relation:** Constrained generation (via `response_format={"type": "json_object"}`) is already used by M0ST to force structured LLM outputs. Constrained decompilation is a future direction.

#### Nova (Jin et al., 2024)

Nova is an LLM-augmented static analysis framework that uses chain-of-thought prompting to guide the LLM through a structured vulnerability analysis reasoning process, improving precision over naive LLM prompting.

**M0ST relation:** M0ST's multi-stage pipeline (static → GNN → pseudocode → LLM) is a form of structured reasoning decomposition similar to Nova's approach. Future work includes chain-of-thought prompting in M0ST's `LLMSemanticAgent`.

---

### 2.5 Dynamic Analysis and Symbolic Execution

#### Valgrind (Nethercote and Seward, 2007)

Valgrind is a dynamic analysis framework that instruments binary code at runtime by translating it into an intermediate representation. Tools built on Valgrind (Memcheck, Callgrind, etc.) detect memory errors and profile runtime behaviour without source.

**Limitation:** High runtime overhead (10–100×); not suitable for malware analysis (sample knows it is instrumented); instrument-and-observe rather than input-generating.

#### Intel PIN (Luk et al., 2005)

PIN is a binary instrumentation platform that injects analysis code into a running process. It provides a high-level API for trace collection, taint tracking, and profiling.

**M0ST relation:** M0ST's `DynamicAgent` uses GDB rather than PIN because GDB supports existing symbol tables and is more flexible for interactive use cases. PIN integration is a future direction for production-grade dynamic analysis.

#### KLEE (Cadar et al., 2008, OSDI)

KLEE is a symbolic execution engine built on the LLVM IR. It explores all feasible execution paths by treating inputs as symbolic variables and using an SMT solver (STP) to find path-satisfying inputs. KLEE famously found 56 bugs in GNU Coreutils on its first run.

**Limitation:** Requires LLVM IR (source or bitcode), not applicable to stripped binaries directly. State explosion limits scalability to large programs.

**M0ST relation:** M0ST's `Z3Agent` performs path-local symbolic reasoning (not whole-program symbolic execution) to check specific safety properties without suffering from state explosion.

#### S2E (Chipounov et al., 2012)

S2E is a platform for writing symbolic execution analysis scripts over full system executions. It can analyse binary programs without source code by executing them in a QEMU VM with symbolic inputs. More scalable than KLEE on binaries but still limited by path explosion.

---

### 2.6 Hybrid and Multi-Agent Security Systems

#### SoK: Eternal War in Memory (Szekeres et al., 2013, S&P)

Surveys memory safety vulnerabilities and defences (stack canaries, ASLR, NX, CFI). Provides a taxonomy of vulnerability classes and their exploitability. Widely cited as the foundational taxonomy work for binary vulnerability analysis.

**M0ST relation:** M0ST's vulnerability detector implements checks for the primary classes identified in this survey: stack overflow, format string, function pointer corruption, integer overflow, and use-after-free.

#### AutoGPT / LangChain Agents (2023)

Early experiments with autonomous LLM agents that use tools (code interpreters, web search, APIs) to solve multi-step problems. Demonstrated that chaining LLM calls with tool use can solve tasks that a single LLM inference cannot.

**Limitation:** General-purpose agents lack domain-specific security tool integration; no structured intermediate representation; hallucinations compound across agent steps.

**M0ST relation:** M0ST's agent architecture is a security-specialised multi-agent system where each agent has a defined role and communicates via a structured PKG rather than unstructured text, avoiding the compounding hallucination problem of general LLM agent chains.

#### CyberAgent / HackerGPT (2024)

Recent work applying LLMs to offensive and defensive security tasks including vulnerability detection, exploit generation, and incident response. These systems demonstrate the potential of LLM reasoning in security but lack formal guarantees or structured data representation.

**M0ST relation:** M0ST provides the structured data layer (PKG) and deterministic analysis pipeline that these LLM-only systems lack, grounding LLM reasoning in verified program facts.

---

## 3. Comparative Analysis

| System        | Static Analysis | ML/GNN                 | LLM                     | Dynamic                 | Unified IR   | Plugin System | Open Source |
| ------------- | --------------- | ---------------------- | ----------------------- | ----------------------- | ------------ | ------------- | ----------- |
| IDA Pro       | ✅ (best)       | ❌                     | ❌                      | ❌                      | ❌           | ✅            | ❌          |
| Ghidra        | ✅              | ❌                     | ❌                      | ❌                      | ❌           | ✅            | ✅          |
| angr          | ✅              | ❌                     | ❌                      | ✅ (symex)              | ✅ (IR)      | ✅            | ✅          |
| GEMINI        | ❌              | ✅ (GNN)               | ❌                      | ❌                      | ❌           | ❌            | Partial     |
| BinaryAI      | ❌              | ✅ (transformer)       | ❌                      | ❌                      | ❌           | ❌            | ❌          |
| Nova          | ✅              | ❌                     | ✅                      | ❌                      | ❌           | ❌            | ❌          |
| LLM4Decompile | ❌              | ✅                     | ✅                      | ❌                      | ❌           | ❌            | ✅          |
| **M0ST**      | **✅**          | **✅ (GAT/SAGE/GINE)** | **✅ (multi-provider)** | **✅ (multi-strategy)** | **✅ (PKG)** | **✅**        | **✅**      |

---

## 4. Research Gaps Identified

### Gap 1: Integration Deficit

All existing tools specialise in one technique. GEMINI does binary similarity. angr does symbolic execution. Ghidra does decompilation. Nova does LLM-guided analysis. **No existing open-source platform unifies static analysis + GNN structural reasoning + LLM semantic reasoning + dynamic tracing + constraint solving into a single, coordinated pipeline.**

An analyst investigating a real binary must run five different tools, manually correlate results, and run them in the right order. There is no platform that orchestrates this automatically.

### Gap 2: No Unified Intermediate Representation

Each tool has its own data model. IDA has its database. angr has its CFG object. GEMINI has its ACFG tensor. **There is no shared, extensible representation that all tools can read from and write to simultaneously.**

This forces analysts to re-extract the same information multiple times (disassemble for Ghidra, disassemble again for angr, extract CFG for GEMINI, etc.) and prevents any tool from benefiting from another tool's results.

### Gap 3: LLMs Operate Without Ground Truth

Current LLM-based binary analysis tools (Nova, GPT-4 prompting experiments) feed raw disassembly to the LLM and ask it to reason. The LLM has no access to:

- Structural facts computed by a GNN
- Previously recovered symbol names
- Dynamic execution traces
- Constraint solving results

**Without grounding, LLM responses are unconstrained by any verified program facts, leading to plausible but incorrect explanations.**

### Gap 4: No AI-Assisted Analysis for Analysts (Interactive + Automated)

Existing ML tools (GEMINI, BinaryAI) are batch processors — you feed them a binary and get back a similarity score or a classification. They are not interactive. **There is no tool that an analyst can have a conversation with about a binary they are currently investigating, combining AI reasoning with their own ad-hoc queries.**

### Gap 5: Scalability of Symbol Recovery

Stripped binary symbol recovery is addressed by individual tools (EKLAVYA for types, function similarity for naming) but always in isolation. **No system combines heuristic rules + embedding similarity + LLM reasoning in a single, confidence-weighted pipeline that degrades gracefully when higher-confidence methods fail.**

### Gap 6: Plugin Ecosystem for Binary Analysis

Unlike source-code SAST tools (Semgrep, CodeQL) which have rich rule/query ecosystems, binary analysis tools have limited extensibility. IDA has scripts but no standardised plugin interface. **There is no binary analysis platform with a simple, standardised plugin API that non-expert users can extend with custom detectors.**

---

## 5. Proposed Methodology

M0ST's methodology directly addresses each identified research gap through five architectural innovations:

### Innovation 1: Program Knowledge Graph (PKG) as Unified IR — addresses Gap 2

M0ST introduces the **Program Knowledge Graph** as the single shared data store for all analysis results. Every agent reads from and writes to the PKG. This eliminates the integration deficit between tools — once radare2 has populated the PKG, the GNN agent can immediately use CFG data, the LLM agent can access previously recovered names, and the plugin system can query instructions.

The PKG is implemented as a typed property graph with:

- 8 node types (Function, BasicBlock, Instruction, Variable, Struct, String, Import, Embedding)
- 8 edge types (CALL, CFG_FLOW, DATA_FLOW, TYPE_RELATION, USES_STRING, IMPORTS, TYPE_OF, SIMILAR_TO)
- Per-entity annotations for analysis results (vulnerability findings, confidence scores, dynamic traces)

**Why this is novel:** Unlike angr's IR (which is an analysis-time intermediate form, not a persistent result store), the PKG is a persistent, queryable knowledge base that accumulates results across all analysis stages.

### Innovation 2: Multi-Agent Orchestration Pipeline — addresses Gap 1 and Gap 4

M0ST implements a two-tier orchestration system:

- `MasterAgent`: classical pipeline in a fixed sequence (static → heuristics → GNN → dynamic → plugins → LLM)
- `PlannerAgent`: intelligent 13-stage pipeline with conditional agent invocation based on available capabilities and binary characteristics

The pipeline is designed so earlier agents enrich the PKG with facts that later agents use. The GNN embedding is available to the LLM. Dynamic traces are available to the constraint solver. Plugin results are available to the semantic summariser.

**Why this is novel:** This is the first binary analysis platform where LLM, GNN, dynamic traces, and constraint solving all share a common knowledge store and are orchestrated by an intelligent planner.

### Innovation 3: Grounded LLM Reasoning — addresses Gap 3

M0ST's `LLMAgent` constructs structured prompts that include:

1. The actual disassembly from radare2
2. Pseudocode from Ghidra/r2
3. GNN-retrieved similar functions (with names) as context
4. Previously recovered symbol names from `SymbolDatabase`
5. Known import names and string references
6. Basic block count, instruction count, loop depth

The LLM is instructed: _"Answer using ONLY data provided. Reference specific addresses, function names, and structural data. Do not fabricate information."_

**Why this is novel:** This "retrieval-augmented" prompting approach for binary analysis mirrors RAG (Retrieval-Augmented Generation) in NLP, but the retrieval is from the PKG rather than a text corpus.

### Innovation 4: Three-Stage Symbol Recovery with Confidence — addresses Gap 5

M0ST's `SymbolRecoveryEngine` implements a cascade strategy:

1. Heuristic rules (import wrapper detection, prologue patterns, naming conventions) — fast, low confidence
2. Embedding similarity search (find named functions with similar GNN embeddings) — medium confidence
3. LLM reasoning (feed disassembly + all PKG context to LLM for naming) — high confidence, highest cost

Results from all three stages are scored and stored. When a downstream agent needs a function name, it retrieves the highest-confidence available name. The system degrades gracefully — if the LLM is not configured, embedding similarity is used; if GNN is not available, heuristics are used.

**Why this is novel:** No existing system combines all three approaches in a single confidence-weighted pipeline.

### Innovation 5: Open Plugin API for Custom Detectors — addresses Gap 6

M0ST introduces a simple, discoverable plugin API:

```python
def analyze(graph_store, func_addr: int) -> dict:
    ...
    return {"category": findings}
```

Any Python file placed in `plugins/` with this function signature is automatically discovered and run by `PluginManager`. Plugins have full read access to the PKG via `graph_store`. Five built-in plugins are provided (anti-debug, crypto, entropy, magic patterns, string decoder). Custom domain-specific detectors can be added without modifying the platform.

**Why this is novel:** Brings the extensibility model of source-code SAST tools (rule/query ecosystem) to binary analysis.

---

## 6. Novelty of M0ST

M0ST's contribution is not any single algorithmic innovation — each individual component (GNN for binary analysis, LLM for code explanation, symbolic execution) exists in prior work. The novelty is in the **integration architecture**:

1. **First open-source platform** to integrate GNN structural analysis, multi-provider LLM reasoning, classical disassembly, dynamic tracing, constraint solving, and vulnerability detection in a single coordinated system.

2. **Program Knowledge Graph** as a live, typed, persistent shared memory for all agents — eliminating the "wall of text to LLM" anti-pattern and enabling grounded, structured reasoning.

3. **Graceful degradation** design: the system works with zero optional dependencies (radare2/GNN/LLM all optional) and improves as more capabilities are added. No other binary analysis platform offers this progressive enhancement model.

4. **Research platform** design: the 7-layer modular architecture, capability system, event bus, and plugin API are designed to enable rapid experimentation with new models, agents, and analysis techniques without modifying the core platform.

---

## 7. Experimentation Plan

The following experiments are planned to validate M0ST's approach. Results from completed experiments will be presented at the external review.

### Experiment 1 — Symbol Recovery Accuracy (Phase 1: Complete)

**Objective:** Measure the accuracy of M0ST's 3-stage symbol recovery on a test set of stripped binaries with known ground-truth symbol tables.

**Method:**

1. Compile 50 open-source programs with debug symbols → ground truth
2. Strip all symbols → input binaries
3. Run M0ST pipeline on stripped binaries
4. Compare predicted function names against ground truth
5. Measure precision@1, precision@5, and MRR (Mean Reciprocal Rank)

**Baseline:** Heuristic-only recovery (stage 1 only)

### Experiment 2 — Vulnerability Detection Precision/Recall

**Objective:** Measure precision and recall of M0ST's vulnerability detector against known vulnerable functions.

**Method:**

1. Collect 100 CVE-confirmed vulnerabilities with corresponding binary functions
2. Run `VulnerabilityDetector` on each binary
3. Measure true positive rate, false positive rate, and F1 score

**Baseline:** Flawfinder (source-level) as an upper bound; grep-based binary heuristics as a lower bound

### Experiment 3 — GNN Embedding Quality

**Objective:** Verify that GNN embeddings produced from CFGs capture semantic similarity.

**Method:**

1. Build a test set of functionally equivalent functions compiled with different compilers (GCC, Clang, MSVC) and optimisation levels (-O0, -O1, -O2, -O3)
2. Compute GNN embeddings for all
3. Measure intra-function cosine similarity vs. inter-function similarity
4. Report ROC-AUC for pairwise matching

**Baseline:** Asm2Vec embeddings; hand-crafted feature vectors without GNN

### Experiment 4 — LLM Semantic Explanation Quality

**Objective:** Evaluate the quality of LLM-generated function explanations when grounded with PKG context versus raw disassembly.

**Method:**

1. Select 30 functions with known behaviour (from documented open-source tools)
2. Generate explanations with (a) raw disassembly only, (b) M0ST full-context prompt
3. Human evaluation on correctness, specificity, and relevance (1–5 scale)

**Baseline:** Direct GPT-4 prompting with disassembly only

---

## 8. References

1. Feng, Y., et al. (2016). _Scalable Graph-based Bug Search for Firmware Images._ ACM CCS.
2. Xu, X., et al. (2017). _Neural Network-based Graph Embedding for Cross-Platform Binary Code Similarity Detection._ IEEE S&P.
3. Ding, S. H., et al. (2019). _Asm2Vec: Boosting Static Representation Robustness for Binary Clone Search against Code Obfuscation and Compiler Optimization._ IEEE S&P.
4. Li, Y., et al. (2021). _PalmTree: Learning an Assembly Language Model for Instruction Embedding._ ACM CCS.
5. Wang, H., et al. (2022). _jTrans: Jump-Aware Transformer for Binary Code Similarity Detection._ ACM ISSTA.
6. Szekeres, L., et al. (2013). _SoK: Eternal War in Memory._ IEEE S&P.
7. Cadar, C., et al. (2008). _KLEE: Unassisted and Automatic Generation of High-Coverage Tests for Complex Systems Programs._ USENIX OSDI.
8. Chipounov, V., et al. (2012). _S2E: A Platform for In-Vivo Multi-Path Analysis of Software Systems._ ASPLOS.
9. Nethercote, N., and Seward, J. (2007). _Valgrind: A Framework for Heavyweight Dynamic Binary Instrumentation._ ACM PLDI.
10. Luk, C. K., et al. (2005). _Pin: Building Customized Program Analysis Tools with Dynamic Instrumentation._ ACM PLDI.
11. Chua, Z. L., et al. (2017). _Neural Nets Can Learn Function Type Signatures From Binaries._ USENIX Security.
12. Armengol-Estapé, J., et al. (2023). _SLaDe: A Portable Small Language Model Decompiler for Optimized Assembly._ arXiv.
13. OpenAI. (2023). _GPT-4 Technical Report._ arXiv.
14. Liu, W., et al. (2020). _Order Matters: Semantic-Aware Neural Networks for Binary Code Similarity Detection._ AAAI.
15. Jiang, X., et al. (2023). _BinaryAI: Binary Software Composition Analysis via Intelligent Binary Source Code Matching._ ICSE.
16. Tan, H., et al. (2024). _LLM4Decompile: Decompiling Binary Code with Large Language Models._ arXiv.
17. Jin, M., et al. (2024). _LLM-Assisted Static Analysis for Detecting Security Vulnerabilities._ arXiv.
18. Radare2 Project. https://github.com/radareorg/radare2
19. Ghidra NSA. https://ghidra-sre.org
20. Veličković, P., et al. (2018). _Graph Attention Networks._ ICLR.
21. Hamilton, W. L., et al. (2017). _Inductive Representation Learning on Large Graphs._ NeurIPS.
22. Xu, K., et al. (2019). _How Powerful are Graph Neural Networks?_ ICLR.

---

_This document is part of the M0ST mini-project first review submission._  
_Prepared: March 2026._
