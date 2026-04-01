"""Quick triplet-embedding evaluation utility for trained M0ST encoders."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

from ai_engine.gnn_models import create_model
from ai_engine.training.dataset_loader import (
    FunctionGraphDataset,
    TripletGraphDataset,
    TripletSample,
    load_metadata_index,
    triplet_collate,
)


def _read_triplets(path: str, id_to_idx: Dict[str, int]) -> List[TripletSample]:
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    out: List[TripletSample] = []
    for item in records:
        a = str(item.get("anchor", ""))
        p = str(item.get("positive", ""))
        n = str(item.get("negative", ""))
        if a in id_to_idx and p in id_to_idx and n in id_to_idx:
            out.append(
                TripletSample(
                    anchor_idx=id_to_idx[a],
                    positive_idx=id_to_idx[p],
                    negative_idx=id_to_idx[n],
                )
            )
    return out


def evaluate(
    encoder_path: str,
    graphs_dir: str,
    metadata_path: str,
    pairs_path: str,
    arch: str = "sage",
    hidden_dim: int = 128,
    embedding_dim: int = 256,
    batch_size: int = 128,
    max_triplets: int = 10000,
    device: str = "cpu",
) -> Dict[str, Any]:
    metadata_entries = load_metadata_index(metadata_path)
    dataset = FunctionGraphDataset(graphs_dir=graphs_dir, metadata_entries=metadata_entries)

    id_to_idx = {p.stem: i for i, p in enumerate(dataset.graph_paths)}
    triplets = _read_triplets(pairs_path, id_to_idx)
    if max_triplets > 0 and len(triplets) > max_triplets:
        triplets = triplets[:max_triplets]

    if not triplets:
        raise ValueError("No usable triplets found for evaluation")

    triplet_ds = TripletGraphDataset(dataset, triplets)
    loader = DataLoader(triplet_ds, batch_size=batch_size, shuffle=False, collate_fn=triplet_collate)

    sample = dataset[0]
    in_dim = int(sample.x.size(-1))

    model = create_model(
        arch=arch,
        in_channels=in_dim,
        hidden_channels=hidden_dim,
        out_channels=embedding_dim,
    )
    state = torch.load(encoder_path, map_location=device)
    model.load_state_dict(state)
    model.to(device)
    model.eval()

    total = 0
    correct_margin = 0
    pos_cos_sum = 0.0
    neg_cos_sum = 0.0

    with torch.no_grad():
        for batch in loader:
            a = batch["anchor"].to(device)
            p = batch["positive"].to(device)
            n = batch["negative"].to(device)

            _, ae = model(a.x, a.edge_index, batch=a.batch)
            _, pe = model(p.x, p.edge_index, batch=p.batch)
            _, ne = model(n.x, n.edge_index, batch=n.batch)

            pos_dist = torch.norm(ae - pe, dim=1)
            neg_dist = torch.norm(ae - ne, dim=1)
            correct_margin += int((pos_dist < neg_dist).sum().item())

            pos_cos_sum += float(F.cosine_similarity(ae, pe, dim=1).sum().item())
            neg_cos_sum += float(F.cosine_similarity(ae, ne, dim=1).sum().item())
            total += int(ae.size(0))

    return {
        "status": "ok",
        "triplets_evaluated": total,
        "margin_accuracy": correct_margin / max(total, 1),
        "avg_pos_cosine": pos_cos_sum / max(total, 1),
        "avg_neg_cosine": neg_cos_sum / max(total, 1),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Evaluate a trained triplet encoder")
    p.add_argument("--encoder-path", required=True)
    p.add_argument("--graphs-dir", default="data/datasets/graphs")
    p.add_argument("--metadata-path", default="data/datasets/metadata/index.json")
    p.add_argument("--pairs-path", default="data/datasets/pairs/train_pairs.json")
    p.add_argument("--arch", default="sage", choices=["gat", "sage", "gine"])
    p.add_argument("--hidden-dim", type=int, default=128)
    p.add_argument("--embedding-dim", type=int, default=256)
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--max-triplets", type=int, default=10000)
    p.add_argument("--device", default="cpu")
    return p


def main() -> int:
    args = _build_parser().parse_args()
    result = evaluate(
        encoder_path=args.encoder_path,
        graphs_dir=args.graphs_dir,
        metadata_path=args.metadata_path,
        pairs_path=args.pairs_path,
        arch=args.arch,
        hidden_dim=args.hidden_dim,
        embedding_dim=args.embedding_dim,
        batch_size=args.batch_size,
        max_triplets=args.max_triplets,
        device=args.device,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
