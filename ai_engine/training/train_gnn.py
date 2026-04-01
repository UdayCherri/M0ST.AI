"""Supervised GNN training entrypoint for M0ST CFG datasets.

Trains a graph encoder using graph-level classification and saves:
- encoder-only weights compatible with GraphAgent
- full classifier weights for continued fine-tuning
- training metadata and label mapping
"""

from __future__ import annotations

import argparse
import json
import os
import random
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import Dataset, Subset

    _TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TORCH_AVAILABLE = False

try:
    from torch_geometric.loader import DataLoader as PyGDataLoader

    _PYG_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PYG_AVAILABLE = False

from ai_engine.gnn_models import create_model, is_available as gnn_is_available
from ai_engine.training.dataset_loader import (
    FunctionGraphDataset,
    build_triplet_loader_from_pairs_file,
    load_metadata_index,
    split_dataset,
)


def _ensure_training_deps() -> None:
    if not _TORCH_AVAILABLE:
        raise RuntimeError("PyTorch is required for GNN training")
    if not _PYG_AVAILABLE or not gnn_is_available():
        raise RuntimeError("PyTorch Geometric is required for GNN training")


def _set_seed(seed: int) -> None:
    random.seed(seed)
    if _TORCH_AVAILABLE:
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)


def _read_metadata_entries(metadata_path: str) -> List[Dict[str, Any]]:
    path = Path(metadata_path)
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, list):
        raise ValueError("metadata file must contain a JSON list of label entries")
    return payload


@dataclass(frozen=True)
class LabelSpace:
    field: str
    index_to_label: List[str]

    @property
    def label_to_index(self) -> Dict[str, int]:
        return {label: idx for idx, label in enumerate(self.index_to_label)}


class LabeledFunctionGraphDataset(Dataset):
    """Wraps function graph data and attaches graph-level labels for supervision."""

    def __init__(
        self,
        graphs_dir: str,
        metadata_entries: List[Dict[str, Any]],
        label_field: str = "source_project",
        max_graphs: Optional[int] = None,
    ):
        _ensure_training_deps()

        self.base_dataset = FunctionGraphDataset(
            graphs_dir=graphs_dir,
            metadata_entries=metadata_entries,
        )
        self.label_field = label_field

        labeled_indices: List[int] = []
        raw_labels: List[str] = []
        for idx in range(len(self.base_dataset)):
            data = self.base_dataset[idx]
            label_value = getattr(data, label_field, None)
            if label_value is None:
                continue
            label_text = str(label_value)
            if not label_text:
                continue
            labeled_indices.append(idx)
            raw_labels.append(label_text)

        if max_graphs is not None:
            labeled_indices = labeled_indices[:max_graphs]
            raw_labels = raw_labels[:max_graphs]

        self.indices = labeled_indices
        label_names = sorted(set(raw_labels))
        self.label_space = LabelSpace(field=label_field, index_to_label=label_names)
        label_to_index = self.label_space.label_to_index
        self.encoded_labels = [label_to_index[label] for label in raw_labels]

        if not self.indices:
            raise ValueError(f"No graphs with label field {label_field!r} were found")

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, index: int):
        data = self.base_dataset[self.indices[index]].clone()
        data.y = torch.tensor(self.encoded_labels[index], dtype=torch.long)
        return data

    @property
    def num_classes(self) -> int:
        return len(self.label_space.index_to_label)

    @property
    def input_dim(self) -> int:
        sample = self[0]
        return int(sample.x.size(-1))


class GraphClassifier(nn.Module):
    """Graph encoder plus graph-level classification head."""

    def __init__(self, encoder: nn.Module, embedding_dim: int, num_classes: int):
        super().__init__()
        self.encoder = encoder
        self.classifier = nn.Linear(embedding_dim, num_classes)

    def forward(self, data):
        node_embeddings, graph_embeddings = self.encoder(
            data.x,
            data.edge_index,
            batch=data.batch,
        )
        logits = self.classifier(graph_embeddings)
        return logits, node_embeddings, graph_embeddings


def train_triplet_encoder(
    graphs_dir: str,
    train_pairs_path: str,
    metadata_path: str = "data/datasets/metadata/index.json",
    arch: str = "sage",
    hidden_dim: int = 128,
    embedding_dim: int = 256,
    epochs: int = 10,
    batch_size: int = 64,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    margin: float = 0.4,
    seed: int = 1337,
    device: str = "auto",
    checkpoint_dir: str = "ai_engine/gnn_models/checkpoints",
    run_name: str = "cfg_encoder_triplet",
) -> Dict[str, Any]:
    _ensure_training_deps()
    _set_seed(seed)

    metadata_entries = load_metadata_index(metadata_path)
    loader = build_triplet_loader_from_pairs_file(
        graphs_dir=graphs_dir,
        train_pairs_path=train_pairs_path,
        metadata_entries=metadata_entries,
        batch_size=batch_size,
        num_workers=0,
    )

    total_triplets = len(getattr(loader, "dataset", []))
    if total_triplets == 0:
        raise ValueError("No triplets found in train_pairs file")

    first_batch = next(iter(loader))
    input_dim = int(first_batch["anchor"].x.size(-1))

    resolved_device = _resolve_device(device)
    encoder = create_model(
        arch=arch,
        in_channels=input_dim,
        hidden_channels=hidden_dim,
        out_channels=embedding_dim,
    )
    encoder.to(resolved_device)

    optimizer = torch.optim.Adam(encoder.parameters(), lr=lr, weight_decay=weight_decay)
    criterion = nn.TripletMarginLoss(margin=margin, p=2)

    history: List[Dict[str, float]] = []
    best_state: Optional[Dict[str, Any]] = None
    best_loss = float("inf")

    for epoch_idx in range(1, epochs + 1):
        encoder.train()
        total_loss = 0.0
        total_items = 0

        for batch in loader:
            anchor = batch["anchor"].to(resolved_device)
            positive = batch["positive"].to(resolved_device)
            negative = batch["negative"].to(resolved_device)

            optimizer.zero_grad()
            _, anchor_emb = encoder(anchor.x, anchor.edge_index, batch=anchor.batch)
            _, positive_emb = encoder(positive.x, positive.edge_index, batch=positive.batch)
            _, negative_emb = encoder(negative.x, negative.edge_index, batch=negative.batch)

            loss = criterion(anchor_emb, positive_emb, negative_emb)
            loss.backward()
            optimizer.step()

            batch_n = int(anchor_emb.size(0))
            total_loss += float(loss.item()) * batch_n
            total_items += batch_n

        epoch_loss = total_loss / max(total_items, 1)
        history.append({"epoch": epoch_idx, "triplet_loss": epoch_loss})
        print(f"Epoch {epoch_idx}/{epochs} triplet_loss={epoch_loss:.4f}")

        if epoch_loss <= best_loss:
            best_loss = epoch_loss
            best_state = deepcopy(encoder.state_dict())

    if best_state is not None:
        encoder.load_state_dict(best_state)

    checkpoint_path = Path(checkpoint_dir)
    checkpoint_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    encoder_path = checkpoint_path / f"{run_name}_{timestamp}_encoder.pt"
    latest_encoder_path = checkpoint_path / f"{run_name}_latest_encoder.pt"
    metadata_out = checkpoint_path / f"{run_name}_{timestamp}_metadata.json"
    latest_metadata_out = checkpoint_path / f"{run_name}_latest_metadata.json"

    torch.save(encoder.state_dict(), encoder_path)
    torch.save(encoder.state_dict(), latest_encoder_path)

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "objective": "triplet",
        "config": {
            "graphs_dir": graphs_dir,
            "train_pairs_path": train_pairs_path,
            "metadata_path": metadata_path,
            "arch": arch,
            "hidden_dim": hidden_dim,
            "embedding_dim": embedding_dim,
            "epochs": epochs,
            "batch_size": batch_size,
            "lr": lr,
            "weight_decay": weight_decay,
            "margin": margin,
            "seed": seed,
            "device": str(resolved_device),
            "triplet_count": total_triplets,
            "input_dim": input_dim,
        },
        "history": history,
        "best_triplet_loss": best_loss,
        "artifacts": {
            "encoder_path": str(encoder_path),
            "latest_encoder_path": str(latest_encoder_path),
        },
    }
    with metadata_out.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    with latest_metadata_out.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    return {
        "status": "ok",
        "objective": "triplet",
        "best_triplet_loss": best_loss,
        "history": history,
        "artifacts": {
            "encoder_path": str(encoder_path),
            "latest_encoder_path": str(latest_encoder_path),
            "metadata_path": str(metadata_out),
            "latest_metadata_path": str(latest_metadata_out),
        },
    }


def _build_loader(dataset, batch_size: int, shuffle: bool) -> PyGDataLoader:
    return PyGDataLoader(dataset, batch_size=batch_size, shuffle=shuffle, num_workers=0)


def _move_batch_to_device(batch, device: torch.device):
    return batch.to(device)


def _run_epoch(model, loader, criterion, optimizer, device: torch.device) -> Dict[str, float]:
    model.train()
    total_loss = 0.0
    total_correct = 0
    total_samples = 0

    for batch in loader:
        batch = _move_batch_to_device(batch, device)
        optimizer.zero_grad()
        logits, _, _ = model(batch)
        loss = criterion(logits, batch.y)
        loss.backward()
        optimizer.step()

        total_loss += float(loss.item()) * int(batch.y.size(0))
        total_correct += int((logits.argmax(dim=1) == batch.y).sum().item())
        total_samples += int(batch.y.size(0))

    return {
        "loss": total_loss / max(total_samples, 1),
        "accuracy": total_correct / max(total_samples, 1),
    }


@torch.no_grad()
def _evaluate(model, loader, criterion, device: torch.device) -> Dict[str, float]:
    model.eval()
    total_loss = 0.0
    total_correct = 0
    total_samples = 0

    for batch in loader:
        batch = _move_batch_to_device(batch, device)
        logits, _, _ = model(batch)
        loss = criterion(logits, batch.y)

        total_loss += float(loss.item()) * int(batch.y.size(0))
        total_correct += int((logits.argmax(dim=1) == batch.y).sum().item())
        total_samples += int(batch.y.size(0))

    return {
        "loss": total_loss / max(total_samples, 1),
        "accuracy": total_correct / max(total_samples, 1),
    }


def _resolve_device(device_arg: str) -> torch.device:
    if device_arg == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(device_arg)


def _save_training_artifacts(
    checkpoint_dir: Path,
    run_name: str,
    model: GraphClassifier,
    label_space: LabelSpace,
    config: Dict[str, Any],
    history: List[Dict[str, float]],
    best_metrics: Dict[str, float],
) -> Dict[str, str]:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{run_name}_{timestamp}"

    encoder_path = checkpoint_dir / f"{stem}_encoder.pt"
    classifier_path = checkpoint_dir / f"{stem}_classifier.pt"
    metadata_path = checkpoint_dir / f"{stem}_metadata.json"
    latest_encoder_path = checkpoint_dir / f"{run_name}_latest_encoder.pt"
    latest_classifier_path = checkpoint_dir / f"{run_name}_latest_classifier.pt"
    latest_metadata_path = checkpoint_dir / f"{run_name}_latest_metadata.json"

    torch.save(model.encoder.state_dict(), encoder_path)
    torch.save(model.state_dict(), classifier_path)
    torch.save(model.encoder.state_dict(), latest_encoder_path)
    torch.save(model.state_dict(), latest_classifier_path)

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_name": run_name,
        "config": config,
        "label_field": label_space.field,
        "label_mapping": {
            str(idx): label for idx, label in enumerate(label_space.index_to_label)
        },
        "history": history,
        "best_metrics": best_metrics,
        "artifacts": {
            "encoder_path": str(encoder_path),
            "classifier_path": str(classifier_path),
            "latest_encoder_path": str(latest_encoder_path),
            "latest_classifier_path": str(latest_classifier_path),
        },
    }
    with metadata_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    with latest_metadata_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    return {
        "encoder_path": str(encoder_path),
        "classifier_path": str(classifier_path),
        "metadata_path": str(metadata_path),
        "latest_encoder_path": str(latest_encoder_path),
        "latest_classifier_path": str(latest_classifier_path),
        "latest_metadata_path": str(latest_metadata_path),
    }


def train_graph_classifier(
    graphs_dir: str,
    metadata_path: str,
    label_field: str = "source_project",
    arch: str = "gat",
    hidden_dim: int = 128,
    embedding_dim: int = 256,
    epochs: int = 5,
    batch_size: int = 64,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    seed: int = 1337,
    device: str = "auto",
    checkpoint_dir: str = "ai_engine/gnn_models/checkpoints",
    run_name: str = "cfg_encoder_source_project",
    max_graphs: Optional[int] = None,
) -> Dict[str, Any]:
    _ensure_training_deps()
    _set_seed(seed)

    metadata_entries = _read_metadata_entries(metadata_path)
    dataset = LabeledFunctionGraphDataset(
        graphs_dir=graphs_dir,
        metadata_entries=metadata_entries,
        label_field=label_field,
        max_graphs=max_graphs,
    )

    train_set, val_set, test_set = split_dataset(dataset, seed=seed)
    train_loader = _build_loader(train_set, batch_size=batch_size, shuffle=True)
    val_loader = _build_loader(val_set, batch_size=batch_size, shuffle=False)
    test_loader = _build_loader(test_set, batch_size=batch_size, shuffle=False)

    resolved_device = _resolve_device(device)
    encoder = create_model(
        arch=arch,
        in_channels=dataset.input_dim,
        hidden_channels=hidden_dim,
        out_channels=embedding_dim,
    )
    model = GraphClassifier(encoder=encoder, embedding_dim=embedding_dim, num_classes=dataset.num_classes)
    model.to(resolved_device)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

    best_model_state: Optional[Dict[str, Any]] = None
    best_val_accuracy = -1.0
    history: List[Dict[str, float]] = []

    for epoch_idx in range(1, epochs + 1):
        train_metrics = _run_epoch(model, train_loader, criterion, optimizer, resolved_device)
        val_metrics = _evaluate(model, val_loader, criterion, resolved_device)
        epoch_metrics = {
            "epoch": epoch_idx,
            "train_loss": train_metrics["loss"],
            "train_accuracy": train_metrics["accuracy"],
            "val_loss": val_metrics["loss"],
            "val_accuracy": val_metrics["accuracy"],
        }
        history.append(epoch_metrics)

        if val_metrics["accuracy"] >= best_val_accuracy:
            best_val_accuracy = val_metrics["accuracy"]
            best_model_state = deepcopy(model.state_dict())

        print(
            f"Epoch {epoch_idx}/{epochs} "
            f"train_loss={train_metrics['loss']:.4f} "
            f"train_acc={train_metrics['accuracy']:.4f} "
            f"val_loss={val_metrics['loss']:.4f} "
            f"val_acc={val_metrics['accuracy']:.4f}"
        )

    if best_model_state is not None:
        model.load_state_dict(best_model_state)

    test_metrics = _evaluate(model, test_loader, criterion, resolved_device)
    print(
        f"Test loss={test_metrics['loss']:.4f} "
        f"test_acc={test_metrics['accuracy']:.4f}"
    )

    config = {
        "graphs_dir": graphs_dir,
        "metadata_path": metadata_path,
        "label_field": label_field,
        "arch": arch,
        "hidden_dim": hidden_dim,
        "embedding_dim": embedding_dim,
        "epochs": epochs,
        "batch_size": batch_size,
        "lr": lr,
        "weight_decay": weight_decay,
        "seed": seed,
        "device": str(resolved_device),
        "max_graphs": max_graphs,
        "dataset_size": len(dataset),
        "num_classes": dataset.num_classes,
        "input_dim": dataset.input_dim,
    }
    artifact_paths = _save_training_artifacts(
        checkpoint_dir=Path(checkpoint_dir),
        run_name=run_name,
        model=model,
        label_space=dataset.label_space,
        config=config,
        history=history,
        best_metrics={
            "best_val_accuracy": best_val_accuracy,
            "test_accuracy": test_metrics["accuracy"],
            "test_loss": test_metrics["loss"],
        },
    )

    return {
        "status": "ok",
        "config": config,
        "history": history,
        "best_val_accuracy": best_val_accuracy,
        "test_accuracy": test_metrics["accuracy"],
        "test_loss": test_metrics["loss"],
        "artifacts": artifact_paths,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train a GNN encoder on M0ST CFG graphs")
    parser.add_argument("--objective", default="triplet", choices=["triplet", "classifier"])
    parser.add_argument("--graphs-dir", default="data/datasets/graphs")
    parser.add_argument("--metadata-path", default="data/datasets/metadata/index.json")
    parser.add_argument("--train-pairs-path", default="data/datasets/pairs/train_pairs.json")
    parser.add_argument("--label-field", default="source_project")
    parser.add_argument("--arch", default="sage", choices=["gat", "sage", "gine"])
    parser.add_argument("--hidden-dim", type=int, default=128)
    parser.add_argument("--embedding-dim", type=int, default=256)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--margin", type=float, default=0.4)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--checkpoint-dir", default="ai_engine/gnn_models/checkpoints")
    parser.add_argument("--run-name", default="cfg_encoder_triplet")
    parser.add_argument("--max-graphs", type=int, default=None)
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.objective == "triplet":
        result = train_triplet_encoder(
            graphs_dir=args.graphs_dir,
            train_pairs_path=args.train_pairs_path,
            metadata_path=args.metadata_path,
            arch=args.arch,
            hidden_dim=args.hidden_dim,
            embedding_dim=args.embedding_dim,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            weight_decay=args.weight_decay,
            margin=args.margin,
            seed=args.seed,
            device=args.device,
            checkpoint_dir=args.checkpoint_dir,
            run_name=args.run_name,
        )
    else:
        result = train_graph_classifier(
            graphs_dir=args.graphs_dir,
            metadata_path=args.metadata_path,
            label_field=args.label_field,
            arch=args.arch,
            hidden_dim=args.hidden_dim,
            embedding_dim=args.embedding_dim,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            weight_decay=args.weight_decay,
            seed=args.seed,
            device=args.device,
            checkpoint_dir=args.checkpoint_dir,
            run_name=args.run_name,
            max_graphs=args.max_graphs,
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())