"""
AI Engine – Training Utilities.

Stubs for model training, fine-tuning, and dataset management
used by the AI Engine layer.
"""

from typing import Any, Dict, List, Optional

from ai_engine.training.dataset_loader import (  # noqa: F401
    ContrastivePair,
    ContrastivePairDataset,
    FunctionGraphDataset,
    build_contrastive_loader,
    build_contrastive_pairs,
    build_embedding_loader,
    build_graph_dataloader,
    build_train_val_test_loaders,
    split_dataset,
)


def train_graph_classifier(*args, **kwargs):  # noqa: F401
    """Lazy import to avoid runpy module re-import warning for train_gnn."""
    from ai_engine.training.train_gnn import train_graph_classifier as _impl

    return _impl(*args, **kwargs)


class TrainingManager:
    """Manages training of GNN and embedding models."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._training_history: List[Dict[str, Any]] = []

    def fine_tune_gnn(self, dataset, epochs: int = 50, lr: float = 1e-3) -> Dict[str, Any]:
        """Fine-tune a GNN model on labelled CFG data."""
        if not isinstance(dataset, dict):
            return {
                "error": "dataset must be a config dict with graphs_dir and metadata_path",
            }

        graphs_dir = dataset.get("graphs_dir")
        metadata_path = dataset.get("metadata_path")
        if not graphs_dir or not metadata_path:
            return {
                "error": "dataset config must include graphs_dir and metadata_path",
            }

        return train_graph_classifier(
            graphs_dir=graphs_dir,
            metadata_path=metadata_path,
            label_field=dataset.get("label_field", "source_project"),
            arch=dataset.get("arch", self.config.get("arch", "gat")),
            hidden_dim=int(dataset.get("hidden_dim", self.config.get("hidden_dim", 128))),
            embedding_dim=int(dataset.get("embedding_dim", self.config.get("embedding_dim", 256))),
            epochs=epochs,
            batch_size=int(dataset.get("batch_size", self.config.get("batch_size", 64))),
            lr=lr,
            weight_decay=float(dataset.get("weight_decay", self.config.get("weight_decay", 1e-4))),
            seed=int(dataset.get("seed", self.config.get("seed", 1337))),
            device=dataset.get("device", self.config.get("device", "auto")),
            checkpoint_dir=dataset.get("checkpoint_dir", self.config.get("checkpoint_dir", "ai_engine/gnn_models/checkpoints")),
            run_name=dataset.get("run_name", "cfg_encoder_source_project"),
            max_graphs=dataset.get("max_graphs"),
        )

    def fine_tune_embeddings(self, pairs, epochs: int = 20) -> Dict[str, Any]:
        """Fine-tune embedding model on similarity pairs."""
        return {"status": "not_implemented", "note": "Embedding fine-tuning placeholder"}

    @property
    def history(self) -> List[Dict[str, Any]]:
        return list(self._training_history)


__all__ = [
    "TrainingManager",
    "ContrastivePair",
    "ContrastivePairDataset",
    "FunctionGraphDataset",
    "build_contrastive_loader",
    "build_contrastive_pairs",
    "build_embedding_loader",
    "build_graph_dataloader",
    "build_train_val_test_loaders",
    "split_dataset",
    "train_graph_classifier",
]
