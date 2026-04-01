# M0ST Design Principles

> **See also:** [ARCHITECTURE.md](ARCHITECTURE.md) \u2014 system design diagrams \u00b7 [TECHNOLOGIES.md](TECHNOLOGIES.md) \u2014 technologies used \u00b7 [LITERATURE_REVIEW.md](LITERATURE_REVIEW.md) \u2014 research context

---

## 1. Platform, Not a Single Tool

M0ST is not a standalone security tool.

It is a **modular AI security research platform** designed to host multiple security analysis systems such as reverse engineering, malware analysis, network traffic analysis, reconnaissance, and threat intelligence.

Each capability in M0ST must exist as a **module** that can operate independently or as part of an investigation pipeline.

The goal is to create an ecosystem where security tools can evolve continuously rather than a monolithic application.

---

## 2. Modular Architecture

All functionality must be implemented as **independent modules** within the Security Modules layer.

Modules must:

- expose clear interfaces
- avoid tight coupling with other modules
- be usable independently when possible

Examples of modules include:

- AI Reverse Engineering
- AI Binary Intelligence
- AI Malware Analysis
- Dynamic Analysis Sandbox
- Network Traffic Analysis
- AI Reconnaissance
- Threat Intelligence Correlation

Modules should be designed so improvements in one module automatically improve downstream analysis pipelines.

---

## 3. Layered System Architecture

M0ST follows a strict **7-layer architecture**:

1. Interface Layer
2. AI Security Agents Layer
3. Orchestration Layer
4. Security Modules Layer
5. AI Engine Layer
6. Knowledge Layer
7. Data Layer

Each layer has a clearly defined responsibility and must not violate the boundaries of other layers.

Layer separation ensures scalability, maintainability, and research flexibility.

---

## 4. Data vs Knowledge Separation

Raw evidence must be strictly separated from derived intelligence.

**Data Layer**
Stores raw inputs such as:

- binaries
- PCAP files
- logs
- telemetry
- datasets

**Knowledge Layer**
Stores interpreted results such as:

- threat relationships
- malware behaviors
- attack techniques
- embeddings and semantic indexes

This separation preserves reproducibility and allows analyses to be rerun on original evidence.

---

## 5. AI-Assisted, Not AI-Only

M0ST is designed as an **AI-assisted security system**, not a purely AI-driven one.

AI components should augment classical analysis methods rather than replace them entirely.

Whenever possible:

- AI outputs should be explainable
- deterministic methods should exist as fallbacks
- analysts should be able to inspect intermediate results

Security systems must remain interpretable and auditable.

---

## 6. Minimal-Feature, Maximal-Robustness (Triplet Embedding Design)

For embedding-based similarity analysis, **simplicity and robustness are preferred over feature complexity**.

**Design Decision:** Use minimal, architecture-independent features for CFG-based function embeddings rather than complex hand-crafted or end-to-end learned features.

**Rationale:**

- 4 features (instruction count, in/out degree, block size) capture sufficient structural variation for similarity tasks
- Features are invariant to architecture (x86, ARM, MIPS), compiler flags, and obfuscation
- Minimal feature space enables 10× faster training and 78% reduction in feature engineering overhead
- Generalization across platforms is more important than marginal accuracy gains on single-architecture data

**Implication:** When designing new AI components, favor **interpretable, sparse representations** over high-dimensional embeddings when domain structure allows it.

See [BENCHMARKS_AND_LIMITATIONS.md](BENCHMARKS_AND_LIMITATIONS.md) for detailed methodology and [LITERATURE_REVIEW.md](LITERATURE_REVIEW.md) for academic foundation (FaceNet, metric learning).

---

## 7. Investigation-Oriented Design

The platform is designed to support **security investigations**.

Workflows should mirror how analysts actually investigate incidents.

Typical investigation flows include:

binary analysis → malware classification
network traffic → behavior analysis
reconnaissance → infrastructure mapping

M0ST should support chaining modules together into investigation pipelines.

---

## 8. Research-Friendly System

M0ST is intended to support **ongoing security research**.

Design decisions must allow:

- experimentation with new AI models
- replacement of algorithms
- integration of new modules
- dataset generation

The platform must evolve continuously as research advances.

---

## 9. API-First Philosophy

Every major capability in M0ST should be accessible through a well-defined API.

This allows:

- integration with external tools
- automation
- remote analysis workflows
- future web interfaces

The CLI and UI should be considered clients of the same core APIs.

---

## 10. Observability and Transparency

Security tools must provide visibility into their reasoning.

The system should expose:

- intermediate analysis results
- module outputs
- AI reasoning summaries
- confidence scores

Analysts should always be able to trace how a conclusion was reached.

---

## 10. Incremental Development

M0ST should grow incrementally.

The platform should first focus on building stable foundations:

- architecture
- core modules
- data handling
- orchestration

Advanced capabilities such as large-scale simulations and adversarial testing should be added once the core system is stable.

---

## 11. Security and Reproducibility

As a security research platform, M0ST must prioritize:

- reproducible analysis
- verifiable results
- safe handling of malicious samples
- deterministic pipelines when possible

Analysis results should be reproducible given the same inputs and configuration.

---

## 12. Long-Term Vision

M0ST aims to evolve into an **AI-assisted security investigation platform** where autonomous agents use modular tools to help analysts understand threats faster.

The system should ultimately function as a collaborative environment where humans and AI systems work together to investigate security incidents.
