"""Dataset loading utilities for M0ST graph embedding training."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import torch
    from torch.utils.data import DataLoader as TorchDataLoader
    from torch.utils.data import Dataset, Subset, random_split

    _TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TORCH_AVAILABLE = False

try:
    from torch_geometric.data import Batch, Data
    from torch_geometric.loader import DataLoader as PyGDataLoader

    _PYG_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PYG_AVAILABLE = False


def _ensure_deps() -> None:
    if not _TORCH_AVAILABLE:
        raise RuntimeError("PyTorch is required for dataset loading")
    if not _PYG_AVAILABLE:
        raise RuntimeError("torch_geometric is required for graph batching")


def _as_tensor(value: Any, dtype: torch.dtype) -> torch.Tensor:
    if isinstance(value, torch.Tensor):
        return value.to(dtype=dtype)
    return torch.tensor(value, dtype=dtype)


def _canonical_function_key(name: Optional[str]) -> str:
    if not name:
        return "unknown"
    cleaned = name.strip().lower()
    if cleaned.startswith("sym."):
        cleaned = cleaned[4:]
    return cleaned


def _minmax_normalize_rows(rows: List[List[float]]) -> List[List[float]]:
    if not rows:
        return rows
    width = len(rows[0])
    mins = [float("inf")] * width
    maxs = [float("-inf")] * width
    for row in rows:
        if len(row) != width:
            continue
        for i, value in enumerate(row):
            if value < mins[i]:
                mins[i] = value
            if value > maxs[i]:
                maxs[i] = value

    out: List[List[float]] = []
    for row in rows:
        if len(row) != width:
            continue
        norm_row: List[float] = []
        for i, value in enumerate(row):
            span = maxs[i] - mins[i]
            if span <= 1e-12:
                norm_row.append(0.0)
            else:
                norm_row.append((value - mins[i]) / span)
        out.append(norm_row)
    return out


def _extract_minimal_node_features(payload: Dict[str, Any]) -> List[List[float]]:
    features = payload.get("node_features")
    if features is None:
        features = payload.get("x")
    if features is None:
        return []

    if hasattr(features, "tolist"):
        features = features.tolist()
    if not isinstance(features, list):
        return []

    # Minimal feature schema:
    # [instruction_count, in_degree, out_degree, basic_block_size]
    out: List[List[float]] = []
    for row in features:
        if hasattr(row, "tolist"):
            row = row.tolist()
        if not isinstance(row, list):
            continue
        float_row = [float(v) for v in row]
        if len(float_row) >= 6:
            instruction_count = float_row[-6]
            in_degree = float_row[-5]
            out_degree = float_row[-4]
            basic_block_size = instruction_count
            out.append([instruction_count, in_degree, out_degree, basic_block_size])
        elif len(float_row) >= 4:
            out.append(float_row[:4])
        elif len(float_row) == 1:
            value = float_row[0]
            out.append([value, 0.0, 0.0, value])

    return _minmax_normalize_rows(out)


class FunctionGraphDataset(Dataset):
    """Dataset backed by serialized function graph pt files."""

    def __init__(
        self,
        graphs_dir: str,
        metadata_entries: Optional[List[Dict[str, Any]]] = None,
        graph_glob: str = "*.pt",
        preload: bool = False,
        lazy_normalize: bool = True,
        cache_dir: Optional[str] = "data/datasets/cache",
        minimal_features: bool = True,
    ):
        _ensure_deps()

        self.graphs_dir = Path(graphs_dir)
        self.graph_paths = sorted(self.graphs_dir.glob(graph_glob))
        self.metadata_map: Dict[str, Dict[str, Any]] = {}
        self.lazy_normalize = lazy_normalize
        self.minimal_features = minimal_features
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        for entry in metadata_entries or []:
            fid = str(entry.get("function_id") or "")
            if fid:
                self.metadata_map[fid] = entry

        self._cache: Dict[int, Data] = {}
        if preload:
            for idx in range(len(self.graph_paths)):
                self._cache[idx] = self._load_graph(idx)

    def __len__(self) -> int:
        return len(self.graph_paths)

    def __getitem__(self, index: int) -> Data:
        if index in self._cache:
            return self._cache[index]
        return self._load_graph(index)

    def _load_graph(self, index: int) -> Data:
        graph_path = self.graph_paths[index]
        cache_hit = self._load_from_cache(graph_path)
        if cache_hit is not None:
            data = cache_hit
        else:
            payload = torch.load(graph_path, map_location="cpu")

            if isinstance(payload, Data):
                data = payload
            elif isinstance(payload, dict):
                data = self._data_from_payload(payload)
            else:
                raise TypeError(f"Unsupported graph payload type: {type(payload).__name__}")
            self._save_to_cache(graph_path, data)

        function_id = getattr(data, "function_id", None)
        if function_id and str(function_id) in self.metadata_map:
            for key, value in self.metadata_map[str(function_id)].items():
                if not hasattr(data, key):
                    setattr(data, key, value)

        return data

    def _data_from_payload(self, payload: Dict[str, Any]) -> Data:
        if self.lazy_normalize and self.minimal_features:
            x = _extract_minimal_node_features(payload)
        else:
            x = payload.get("node_features")
            if x is None:
                x = payload.get("x")

        edge_index = payload.get("edge_index")
        if edge_index is None:
            edge_index = [[], []]

        x_tensor = _as_tensor(x if x is not None else [], dtype=torch.float32)
        if x_tensor.ndim == 1:
            x_tensor = x_tensor.unsqueeze(0)
        if x_tensor.numel() == 0:
            x_tensor = torch.zeros((1, 4), dtype=torch.float32)

        edge_tensor = _as_tensor(edge_index, dtype=torch.long)
        if edge_tensor.numel() == 0:
            edge_tensor = torch.zeros((2, 0), dtype=torch.long)
        elif edge_tensor.ndim != 2:
            edge_tensor = edge_tensor.reshape(2, -1)

        data = Data(x=x_tensor, edge_index=edge_tensor)
        for key in (
            "function_id",
            "function_name",
            "source",
            "source_dataset",
            "compiler",
            "optimization_level",
            "binary_path",
            "binary_name",
            "project_name",
            "num_nodes",
        ):
            if key in payload:
                setattr(data, key, payload[key])
        return data

    def _cache_file_path(self, graph_path: Path) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"{graph_path.stem}.data.pt"

    def _load_from_cache(self, graph_path: Path) -> Optional[Data]:
        cache_path = self._cache_file_path(graph_path)
        if cache_path is None or not cache_path.exists():
            return None
        try:
            payload = torch.load(cache_path, map_location="cpu")
        except Exception:
            return None
        return payload if isinstance(payload, Data) else None

    def _save_to_cache(self, graph_path: Path, data: Data) -> None:
        cache_path = self._cache_file_path(graph_path)
        if cache_path is None:
            return
        try:
            torch.save(data, cache_path)
        except Exception:
            return


def load_metadata_index(metadata_index_path: str) -> List[Dict[str, Any]]:
    path = Path(metadata_index_path)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def build_graph_dataloader(
    dataset: Dataset,
    batch_size: int = 32,
    shuffle: bool = True,
    num_workers: int = 0,
) -> PyGDataLoader:
    _ensure_deps()
    return PyGDataLoader(dataset, batch_size=batch_size, shuffle=shuffle, num_workers=num_workers)


def split_dataset(
    dataset: Dataset,
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    seed: int = 1337,
) -> Tuple[Subset, Subset, Subset]:
    _ensure_deps()

    total = len(dataset)
    if total == 0:
        return Subset(dataset, []), Subset(dataset, []), Subset(dataset, [])

    ratio_sum = train_ratio + val_ratio + test_ratio
    if abs(ratio_sum - 1.0) > 1e-6:
        raise ValueError("train_ratio + val_ratio + test_ratio must equal 1.0")

    train_len = int(total * train_ratio)
    val_len = int(total * val_ratio)
    test_len = total - train_len - val_len

    generator = torch.Generator().manual_seed(seed)
    return random_split(dataset, [train_len, val_len, test_len], generator=generator)


def build_train_val_test_loaders(
    graphs_dir: str,
    metadata_entries: Optional[List[Dict[str, Any]]] = None,
    batch_size: int = 32,
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    seed: int = 1337,
    num_workers: int = 0,
) -> Dict[str, PyGDataLoader]:
    dataset = FunctionGraphDataset(graphs_dir=graphs_dir, metadata_entries=metadata_entries)
    train_set, val_set, test_set = split_dataset(
        dataset=dataset,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        test_ratio=test_ratio,
        seed=seed,
    )
    return {
        "train": build_graph_dataloader(train_set, batch_size=batch_size, shuffle=True, num_workers=num_workers),
        "val": build_graph_dataloader(val_set, batch_size=batch_size, shuffle=False, num_workers=num_workers),
        "test": build_graph_dataloader(test_set, batch_size=batch_size, shuffle=False, num_workers=num_workers),
    }


@dataclass(frozen=True)
class ContrastivePair:
    left_idx: int
    right_idx: int
    label: int


@dataclass(frozen=True)
class TripletSample:
    anchor_idx: int
    positive_idx: int
    negative_idx: int


class ContrastivePairDataset(Dataset):
    def __init__(self, base_dataset: FunctionGraphDataset, pairs: Sequence[ContrastivePair]):
        _ensure_deps()
        self.base_dataset = base_dataset
        self.pairs = list(pairs)

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, index: int) -> Dict[str, Any]:
        pair = self.pairs[index]
        return {
            "left": self.base_dataset[pair.left_idx],
            "right": self.base_dataset[pair.right_idx],
            "label": torch.tensor(pair.label, dtype=torch.float32),
        }


class TripletGraphDataset(Dataset):
    def __init__(self, base_dataset: FunctionGraphDataset, triplets: Sequence[TripletSample]):
        _ensure_deps()
        self.base_dataset = base_dataset
        self.triplets = list(triplets)

    def __len__(self) -> int:
        return len(self.triplets)

    def __getitem__(self, index: int) -> Dict[str, Data]:
        sample = self.triplets[index]
        return {
            "anchor": self.base_dataset[sample.anchor_idx],
            "positive": self.base_dataset[sample.positive_idx],
            "negative": self.base_dataset[sample.negative_idx],
        }


def build_contrastive_pairs(
    dataset: FunctionGraphDataset,
    max_positive_per_anchor: int = 4,
    max_negative_per_anchor: int = 4,
    seed: int = 1337,
) -> List[ContrastivePair]:
    _ensure_deps()
    rng = random.Random(seed)
    groups: Dict[str, List[int]] = {}

    for idx in range(len(dataset)):
        data = dataset[idx]
        fn_name = _canonical_function_key(getattr(data, "function_name", None))
        groups.setdefault(fn_name, []).append(idx)

    group_keys = list(groups.keys())
    pairs: List[ContrastivePair] = []

    for key in group_keys:
        anchors = groups[key]
        negatives_pool = [i for g in group_keys if g != key for i in groups[g]]

        for anchor in anchors:
            positive_candidates = [i for i in anchors if i != anchor]
            rng.shuffle(positive_candidates)
            for pos_idx in positive_candidates[:max_positive_per_anchor]:
                pairs.append(ContrastivePair(anchor, pos_idx, 1))

            if negatives_pool:
                sampled_negatives = rng.sample(negatives_pool, k=min(max_negative_per_anchor, len(negatives_pool)))
                for neg_idx in sampled_negatives:
                    pairs.append(ContrastivePair(anchor, neg_idx, 0))

    rng.shuffle(pairs)
    return pairs


def build_triplet_samples(
    dataset: FunctionGraphDataset,
    max_triplets_per_anchor: int = 4,
    seed: int = 1337,
) -> List[TripletSample]:
    _ensure_deps()
    rng = random.Random(seed)
    groups: Dict[str, List[int]] = {}

    for idx in range(len(dataset)):
        data = dataset[idx]
        key = _canonical_function_key(getattr(data, "function_name", None))
        groups.setdefault(key, []).append(idx)

    keys = list(groups.keys())
    triplets: List[TripletSample] = []

    for key in keys:
        anchor_group = groups[key]
        if len(anchor_group) < 2:
            continue
        negative_pool = [idx for other_key in keys if other_key != key for idx in groups[other_key]]
        if not negative_pool:
            continue

        for anchor in anchor_group:
            positives = [idx for idx in anchor_group if idx != anchor]
            if not positives:
                continue
            rng.shuffle(positives)
            for pos_idx in positives[:max_triplets_per_anchor]:
                neg_idx = rng.choice(negative_pool)
                triplets.append(TripletSample(anchor_idx=anchor, positive_idx=pos_idx, negative_idx=neg_idx))

    rng.shuffle(triplets)
    return triplets


def contrastive_collate(batch_items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    _ensure_deps()
    return {
        "left": Batch.from_data_list([item["left"] for item in batch_items]),
        "right": Batch.from_data_list([item["right"] for item in batch_items]),
        "label": torch.stack([item["label"] for item in batch_items], dim=0),
    }


def triplet_collate(batch_items: Sequence[Dict[str, Data]]) -> Dict[str, Batch]:
    _ensure_deps()
    return {
        "anchor": Batch.from_data_list([item["anchor"] for item in batch_items]),
        "positive": Batch.from_data_list([item["positive"] for item in batch_items]),
        "negative": Batch.from_data_list([item["negative"] for item in batch_items]),
    }


def build_contrastive_loader(
    graphs_dir: str,
    metadata_entries: Optional[List[Dict[str, Any]]] = None,
    batch_size: int = 32,
    max_positive_per_anchor: int = 4,
    max_negative_per_anchor: int = 4,
    seed: int = 1337,
    num_workers: int = 0,
) -> TorchDataLoader:
    _ensure_deps()
    dataset = FunctionGraphDataset(graphs_dir=graphs_dir, metadata_entries=metadata_entries)
    pairs = build_contrastive_pairs(
        dataset,
        max_positive_per_anchor=max_positive_per_anchor,
        max_negative_per_anchor=max_negative_per_anchor,
        seed=seed,
    )
    pair_dataset = ContrastivePairDataset(dataset, pairs)
    return TorchDataLoader(
        pair_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        collate_fn=contrastive_collate,
    )


def build_triplet_loader(
    graphs_dir: str,
    metadata_entries: Optional[List[Dict[str, Any]]] = None,
    batch_size: int = 32,
    max_triplets_per_anchor: int = 4,
    seed: int = 1337,
    num_workers: int = 0,
) -> TorchDataLoader:
    _ensure_deps()
    dataset = FunctionGraphDataset(graphs_dir=graphs_dir, metadata_entries=metadata_entries)
    triplets = build_triplet_samples(dataset, max_triplets_per_anchor=max_triplets_per_anchor, seed=seed)
    triplet_dataset = TripletGraphDataset(dataset, triplets)
    return TorchDataLoader(
        triplet_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        collate_fn=triplet_collate,
    )


def build_triplet_loader_from_pairs_file(
    graphs_dir: str,
    train_pairs_path: str,
    metadata_entries: Optional[List[Dict[str, Any]]] = None,
    batch_size: int = 32,
    num_workers: int = 0,
) -> TorchDataLoader:
    _ensure_deps()
    dataset = FunctionGraphDataset(graphs_dir=graphs_dir, metadata_entries=metadata_entries)

    pair_records = json.loads(Path(train_pairs_path).read_text(encoding="utf-8"))
    id_to_idx: Dict[str, int] = {}
    for idx, path in enumerate(dataset.graph_paths):
        fid = path.stem
        id_to_idx[fid] = idx

    triplets: List[TripletSample] = []
    for item in pair_records:
        anchor = str(item.get("anchor", ""))
        positive = str(item.get("positive", ""))
        negative = str(item.get("negative", ""))
        if anchor in id_to_idx and positive in id_to_idx and negative in id_to_idx:
            triplets.append(
                TripletSample(
                    anchor_idx=id_to_idx[anchor],
                    positive_idx=id_to_idx[positive],
                    negative_idx=id_to_idx[negative],
                )
            )

    triplet_dataset = TripletGraphDataset(dataset, triplets)
    return TorchDataLoader(
        triplet_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        collate_fn=triplet_collate,
    )


def build_embedding_loader(
    graphs_dir: str,
    metadata_entries: Optional[List[Dict[str, Any]]] = None,
    batch_size: int = 32,
    max_positive_per_anchor: int = 4,
    max_negative_per_anchor: int = 4,
    seed: int = 1337,
    num_workers: int = 0,
) -> TorchDataLoader:
    """Backward-compatible alias for the legacy embedding pair loader API."""
    return build_contrastive_loader(
        graphs_dir=graphs_dir,
        metadata_entries=metadata_entries,
        batch_size=batch_size,
        max_positive_per_anchor=max_positive_per_anchor,
        max_negative_per_anchor=max_negative_per_anchor,
        seed=seed,
        num_workers=num_workers,
    )
