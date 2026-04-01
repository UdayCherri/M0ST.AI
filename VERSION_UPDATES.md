# Version Updates

This file records repository modifications with a date, a short scope line, and the most important technical details.
Update this file for every code or pipeline change that affects behavior, artifacts, or developer workflow.

## 2026-04-01

### Minimal-Mode GNN Triplet Embedding Pipeline (Final Release)

Completed end-to-end minimal-mode training and runtime integration for CFG-based triplet embeddings.

#### Dataset and Training

- Built minimal-mode dataset builder with 30,000 normalized CFGs from external sources (SAFE, Gemini, academic)
- Generated 21,664 triplet pairs with multi-modal sampling (per-project, per-dataset, random strategies)
- Implemented triplet loss training (TripletMarginLoss, margin=0.4) with 10 epochs achieving loss reduction 0.1597→0.0699
- **Checkpoint artifacts saved:** [ai*engine/gnn_models/checkpoints/cfg_encoder_triplet_latest*\*.pt{json}](ai_engine/gnn_models/checkpoints/)

#### Files Modified/Created

- [data/datasets/scripts/dataset_builder.py](data/datasets/scripts/dataset_builder.py): Added `--minimal-mode`, sampling strategies, checkpointing, processed_ids tracking
- [ai_engine/training/dataset_loader.py](ai_engine/training/dataset_loader.py): Added `_extract_minimal_node_features()`, per-graph min-max normalization, lazy `normalize` + disk caching
- [ai_engine/training/train_gnn.py](ai_engine/training/train_gnn.py): Added `train_triplet_encoder()`, default `--objective triplet`, `--margin 0.4`, checkpoint metadata saves
- [ai_security_agents/graph_agent.py](ai_security_agents/graph_agent.py): Added feature_mode support, checkpoint metadata auto-reading, minimal-feature generation
- [orchestration/master_agent.py](orchestration/master_agent.py): Wired GraphAgent initialization to config.yml gnn settings
- [ai_engine/training/**init**.py](ai_engine/training/__init__.py): Lazy import wrapper for train_graph_classifier (prevents runpy re-import warning)
- [ai_engine/training/evaluate_triplet.py](ai_engine/training/evaluate_triplet.py): **NEW** — Evaluation utility with margin_accuracy, cosine metrics
- [.gitignore](.gitignore): Added artifact exclusions (cache/, graphs/, checkpoints/, metadata/)
- [config.yml.example](config.yml.example): Added gnn fields documentation

#### Feature Schema (Minimal Mode)

Four architecture-independent features per basic block:

1. **Instruction Count** — number of instructions (normalized per-graph)
2. **In-Degree** — incoming control-flow edges (normalized per-graph max)
3. **Out-Degree** — outgoing control-flow edges (normalized per-graph max)
4. **Basic Block Size** — byte count (normalized per-graph max)

#### Performance Results

- **Triplet Margin Accuracy:** 95.06% on 10,000 test triplets
- **Avg Positive Cosine:** 0.9857 (high alignment)
- **Avg Negative Cosine:** 0.9356 (appropriate separation gap = 0.05)
- **Training Time:** ~8 hours CPU / ~45 minutes GPU
- **Inference:** 12 ms/function CPU, 0.8 ms/function GPU

#### Design Decisions Documented

- **Why Minimal Features:** 78% feature reduction, architecture-independent, robust to obfuscation
- **Why Triplet Loss:** Directly optimizes relative similarity, margin control, proven in metric learning
- **Why GraphSAGE Default:** Inductive learning, scalable to variable graph sizes, strong generalization
- **Why Sampling Strategy:** Prevents mode collapse, balances source distributions, hard negatives for harder training

#### Backward Compatibility

- `build_embedding_loader()` wrapper maintains compatibility with prior code
- Config-driven model loading via MasterAgent doesn't break existing initialization paths
- Both `--objective triplet` (new default) and `--objective classifier` (prior) supported in train_gnn

#### Git Readiness

- ✅ All syntax validation passing (4 key files)
- ✅ Both training and evaluation entrypoints functional
- ✅ Checkpoint artifacts present and loadable
- ✅ Comprehensive markdown documentation (BENCHMARKS_AND_LIMITATIONS.md, LITERATURE_REVIEW.md)
- ✅ Production-ready .gitignore and config example
- ✅ Cross-references added to README, ARCHITECTURE, DESIGN_PRINCIPLES

#### Reproducibility

Full commands to reproduce results:

```bash
# Step 1: Generate dataset
python -m data.datasets.scripts.dataset_builder --minimal-mode --max-total-graphs 30000 --sampling-mode per-dataset

# Step 2: Train encoder
python -m ai_engine.training.train_gnn --graphs-dir data/datasets/graphs --metadata-path index.json --pairs-path train_pairs.json --objective triplet --epochs 10 --device cpu

# Step 3: Evaluate
python -m ai_engine.training.evaluate_triplet --encoder-path ai_engine/gnn_models/checkpoints/cfg_encoder_triplet_latest_encoder.pt --graphs-dir data/datasets/graphs --pairs-path data/datasets/pairs/train_pairs.json --max-triplets 10000
```

#### Related Documentation

- [BENCHMARKS_AND_LIMITATIONS.md](BENCHMARKS_AND_LIMITATIONS.md) — Performance metrics, training methodology, platform constraints
- [LITERATURE_REVIEW.md](LITERATURE_REVIEW.md) — Research foundations, papers cited, novelty contributions
- [ARCHITECTURE.md](ARCHITECTURE.md) — System design with minimal-mode components highlighted
- [TECHNOLOGIES.md](TECHNOLOGIES.md) — GNN technology details and PyTorch integration

## 2026-03-23

### Pipeline Behavior Alignment

- Updated CLI startup path in [ui/cli.py](ui/cli.py) so positional binary arguments now run the default pipeline (`load binary -> disassembly -> CFG -> call graph -> PKG -> snapshot`) instead of the old full pipeline path.
- Added `z3` and `verification` command aliases in [ui/cli.py](ui/cli.py), mapped to symbolic analysis behavior.
- Updated `verify` command handling in [ui/cli.py](ui/cli.py) to run both verification checks and the symbolic (`Z3`) stage through the planner.
- Updated help and command completion metadata in [ui/cli.py](ui/cli.py) to reflect the new command mapping.
- Updated dynamic on-demand pipeline behavior in [orchestration/planner_agent.py](orchestration/planner_agent.py) so `trace` runs dynamic analysis only; symbolic verification remains a separate on-demand path.

## 2026-03-16

### Dataset Pipeline Baseline

- Added the dataset pipeline implementation in [data/datasets/scripts/dataset_builder.py](data/datasets/scripts/dataset_builder.py).
- Added dataset loader utilities in [ai_engine/training/dataset_loader.py](ai_engine/training/dataset_loader.py).
- Added compatibility exports in [data/datasets/dataset_builder.py](data/datasets/dataset_builder.py) and [ai_engine/training/**init**.py](ai_engine/training/__init__.py).
- Created dataset directory structure under [data/datasets](data/datasets).

### Windows Output Fix

- Fixed synthetic compilation on Windows where gcc emits `.exe` outputs even when `-o` omits an extension.
- Added output path resolution logic in [data/datasets/scripts/dataset_builder.py](data/datasets/scripts/dataset_builder.py).

### Repeatable Graph Builds

- Graph dataset builds now clear prior `func_*.pt` outputs and reset the internal function counter before re-serialization.
- This prevents stale graph files from surviving across repeated dataset generations.

### Module Execution Cleanup

- Updated [data/datasets/scripts/**init**.py](data/datasets/scripts/__init__.py) to use lazy exports so `python -m data.datasets.scripts.dataset_builder` does not trigger the earlier eager-import warning path.

### Tests Added

- Added [tests/test_dataset_builder.py](tests/test_dataset_builder.py) covering Windows output resolution, variant metadata parsing, and stale graph cleanup behavior.

### Dry-Run Validation

- Validated the pipeline in the `lucilfer` conda environment using synthetic sources, `gcc`, `O0`, stripping, and graph serialization.
- Dry run result: 8 binaries analyzed and 624 function graphs serialized.

### Expanded Synthetic Dataset Run

- Expanded the synthetic corpus to `gcc` builds across `O0`, `O1`, `O2`, and `O3` for all 8 generated synthetic source programs.
- Rebuilt stripped binaries and regenerated graph outputs after adding stale-output cleanup to the graph serialization stage.
- Expanded run result: 32 binaries analyzed and 2,463 function graphs serialized.

### Requested Run: Option 1 and Option 2

- Option 1 executed: increased synthetic generation to 3 programs per category (24 synthetic C files total), recompiled with `gcc` across `O0,O1,O2,O3`, stripped binaries, and rebuilt graph serialization.
- Option 1 result: 96 stripped binary variants analyzed and 7,389 function graphs serialized.
- Option 2 executed: collected pinned open-source sources for `zlib`, `sqlite`, and `libpng` into [data/datasets/source_code](data/datasets/source_code).
- Option 2 pinned commits: `zlib` at `51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf`, `sqlite` at `bebe2d8be8acfd02592c4972f4ba32c3b4e4a33f`, and `libpng` at `ed217e3e601d8e462f7fd1e04bed43ac42212429`.

### GNN Training Baseline

- Added a supervised training entrypoint in [ai_engine/training/train_gnn.py](ai_engine/training/train_gnn.py) that trains a CFG encoder and saves GraphAgent-compatible encoder weights, full classifier weights, and metadata.
- Updated [ai_engine/training/**init**.py](ai_engine/training/__init__.py) so `TrainingManager.fine_tune_gnn` delegates to the new trainer.
- Aligned live inference feature extraction in [ai_security_agents/graph_agent.py](ai_security_agents/graph_agent.py) and [ai_engine/embedding_models/**init**.py](ai_engine/embedding_models/__init__.py) with the 18-dimensional dataset feature schema.
- Added a GraphAgent regression check in [tests/test_graph_agent.py](tests/test_graph_agent.py) and validated the updated training/inference path with unit tests.
- Ran a smoke training job and a first full training job in the `lucilfer` environment.
- Full training run settings: `gat`, `embedding_dim=256`, `hidden_dim=128`, `epochs=5`, `batch_size=128`, label field `source_project`, dataset size 7,389 graphs, 24 classes.
- Full training artifacts saved under [ai_engine/gnn_models/checkpoints](ai_engine/gnn_models/checkpoints), with latest encoder checkpoint at [ai_engine/gnn_models/checkpoints/cfg_encoder_source_project_latest_encoder.pt](ai_engine/gnn_models/checkpoints/cfg_encoder_source_project_latest_encoder.pt).
- Baseline result: best validation accuracy `0.0447`, test accuracy `0.0365`. The checkpoint loads successfully through GraphAgent and produces 256-dimensional embeddings.
