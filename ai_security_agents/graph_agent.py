"""
M0ST Graph Agent — GNN-based structural analysis of control-flow graphs.

Converts CFG data from the PKG into PyTorch Geometric tensors,
runs a GNN model (GAT/GraphSAGE/GINE), and produces per-node and
whole-graph embedding vectors for downstream LLM fusion.
"""

import base64
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.capabilities import Capability

try:
    import torch
    import numpy as np
    from torch_geometric.data import Data

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False

try:
    from ai_engine.gnn_models import create_model, is_available as _gnn_available
except ImportError:
    _gnn_available = lambda: False
    create_model = None


_OPCODE_CATEGORIES = {
    "mov": 0, "lea": 0, "movzx": 0, "movsx": 0, "cmov": 0,
    "push": 1, "pop": 1,
    "add": 2, "sub": 2, "inc": 2, "dec": 2, "neg": 2, "adc": 2, "sbb": 2,
    "mul": 3, "imul": 3, "div": 3, "idiv": 3,
    "and": 4, "or": 4, "xor": 4, "not": 4, "shl": 4, "shr": 4, "sar": 4,
    "rol": 4, "ror": 4,
    "cmp": 5, "test": 5,
    "jmp": 6, "je": 6, "jne": 6, "jg": 6, "jge": 6, "jl": 6, "jle": 6,
    "ja": 6, "jb": 6, "jc": 6,
    "call": 7, "bl": 7, "blr": 7,
    "ret": 8, "retn": 8, "retq": 8, "leave": 8,
    "nop": 9,
    "syscall": 10, "int": 10, "svc": 10,
}
_NUM_OPCODE_CATS = 12


class GraphAgent:
    """GNN-based structural analysis agent for M0ST."""

    CAPABILITIES = {Capability.GNN_INFERENCE, Capability.STATIC_READ}

    def __init__(
        self,
        graph_store,
        model_path: Optional[str] = None,
        arch: str = "gat",
        embedding_dim: int = 256,
        device: str = "cpu",
        feature_mode: str = "full",
        input_dim: Optional[int] = None,
        hidden_dim: int = 128,
    ):
        self.g = graph_store
        self.arch = self._resolve_arch_name(arch)
        self.embedding_dim = embedding_dim
        self.device = device
        self.model = None
        self.feature_mode = (feature_mode or "full").strip().lower()
        self._node_feature_dim = int(input_dim) if input_dim else (4 if self.feature_mode == "minimal" else _NUM_OPCODE_CATS + 6)

        if model_path:
            md = self._load_checkpoint_metadata(model_path)
            cfg = md.get("config", {}) if isinstance(md, dict) else {}
            if isinstance(cfg, dict):
                self.arch = self._resolve_arch_name(str(cfg.get("arch", self.arch)))
                self.embedding_dim = int(cfg.get("embedding_dim", self.embedding_dim))
                self._node_feature_dim = int(cfg.get("input_dim", self._node_feature_dim))
                hidden_dim = int(cfg.get("hidden_dim", hidden_dim))
                if self._node_feature_dim == 4:
                    self.feature_mode = "minimal"

        if _TORCH_AVAILABLE and _gnn_available():
            try:
                self.model = create_model(
                    arch=self.arch,
                    in_channels=self._node_feature_dim,
                    hidden_channels=hidden_dim,
                    out_channels=self.embedding_dim,
                )
                if model_path:
                    state_dict = torch.load(model_path, map_location=device)
                    self.model.load_state_dict(state_dict)
                self.model.to(device)
                self.model.eval()
            except Exception as e:
                print(f"[GraphAgent] Could not load GNN model: {e}")
                self.model = None

    @staticmethod
    def _resolve_arch_name(arch: str) -> str:
        value = (arch or "gat").strip().lower()
        if value in {"graphsage", "sage"}:
            return "sage"
        if value in {"gine", "gat"}:
            return value
        return "gat"

    @staticmethod
    def _load_checkpoint_metadata(model_path: str) -> Dict[str, Any]:
        path = Path(model_path)
        # Prefer explicit latest metadata if paired latest encoder is used.
        if path.name.endswith("_latest_encoder.pt"):
            candidate = path.with_name(path.name.replace("_latest_encoder.pt", "_latest_metadata.json"))
            if candidate.exists():
                try:
                    return json.loads(candidate.read_text(encoding="utf-8"))
                except Exception:
                    return {}

        # Fallback for timestamped encoder naming.
        stem = path.stem
        if stem.endswith("_encoder"):
            candidate = path.with_name(stem[:-8] + "_metadata.json")
            if candidate.exists():
                try:
                    return json.loads(candidate.read_text(encoding="utf-8"))
                except Exception:
                    return {}
        return {}

    def analyse_function(self, func_addr: int) -> Dict[str, Any]:
        blocks = self.g.fetch_basic_blocks(func_addr)
        edges = self.g.fetch_flow_edges(func_addr)
        if not blocks:
            return self._empty_result(func_addr)
        data = self._build_graph_data(func_addr, blocks, edges)
        if self.model is not None and _TORCH_AVAILABLE:
            return self._run_gnn(func_addr, data, blocks)
        else:
            return self._fallback_embedding(func_addr, data, blocks, edges)

    def analyse_all_functions(self) -> Dict[int, Dict[str, Any]]:
        results = {}
        for func in self.g.fetch_functions():
            addr = func.get("addr")
            if addr is None:
                continue
            results[addr] = self.analyse_function(addr)
        return results

    def get_graph_embedding_for_llm(self, func_addr: int) -> str:
        result = self.analyse_function(func_addr)
        return json.dumps(result.get("graph_embedding", []))

    def get_graph_embedding_b64(self, func_addr: int) -> str:
        result = self.analyse_function(func_addr)
        return result.get("graph_embedding_b64", "")

    def find_similar(self, func_addr: int, top_k: int = 5) -> List[Dict[str, Any]]:
        """Find structurally similar functions by cosine similarity of graph embeddings."""
        target = self.analyse_function(func_addr)
        target_emb = target.get("graph_embedding", [])
        if not target_emb or all(v == 0.0 for v in target_emb):
            return []

        all_results = self.analyse_all_functions()
        similarities = []
        for addr, result in all_results.items():
            if addr == func_addr:
                continue
            emb = result.get("graph_embedding", [])
            if not emb or len(emb) != len(target_emb):
                continue
            sim = self._cosine_similarity(target_emb, emb)
            similarities.append({"addr": addr, "similarity": round(sim, 4),
                                 "node_count": result.get("node_count", 0),
                                 "edge_count": result.get("edge_count", 0)})
        similarities.sort(key=lambda x: x["similarity"], reverse=True)
        return similarities[:top_k]

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def _build_graph_data(self, func_addr: int, blocks: List[int], edges: List[Tuple[int, int]]):
        block_to_idx = {bb: i for i, bb in enumerate(blocks)}
        loop_depths = self._estimate_loop_depths(blocks, edges)
        in_degree = {bb: 0 for bb in blocks}
        out_degree = {bb: 0 for bb in blocks}
        for src, dst in edges:
            if src in out_degree:
                out_degree[src] += 1
            if dst in in_degree:
                in_degree[dst] += 1

        node_features = []
        for bb in blocks:
            feat = self._compute_block_features(bb, edges, in_degree, out_degree, loop_depths)
            node_features.append(feat)
        src_list, dst_list = [], []
        for s, d in edges:
            if s in block_to_idx and d in block_to_idx:
                src_list.append(block_to_idx[s])
                dst_list.append(block_to_idx[d])
        if _TORCH_AVAILABLE:
            x = torch.tensor(node_features, dtype=torch.float32)
            if src_list:
                edge_index = torch.tensor([src_list, dst_list], dtype=torch.long)
            else:
                edge_index = torch.zeros((2, 0), dtype=torch.long)
            return Data(x=x, edge_index=edge_index)
        else:
            return {"x": node_features, "edge_index": [src_list, dst_list], "num_nodes": len(blocks)}

    def _compute_block_features(
        self,
        bb_addr: int,
        all_edges: List[Tuple[int, int]],
        in_degree: Dict[int, int],
        out_degree: Dict[int, int],
        loop_depths: Dict[int, int],
    ) -> List[float]:
        insns = self.g.fetch_block_instructions(bb_addr)
        hist = [0.0] * _NUM_OPCODE_CATS
        call_count = 0
        branch_count = 0
        for insn in insns:
            mnem = (insn.get("mnemonic") or "").lower()
            cat = _OPCODE_CATEGORIES.get(mnem, 11)
            hist[cat] += 1.0
            if mnem.startswith("call") or mnem in {"bl", "blr"}:
                call_count += 1
            if (mnem.startswith("j") and mnem not in {"jmp"}) or mnem in {"jmp", "b", "beq", "bne"}:
                branch_count += 1
        total = sum(hist)
        if total > 0:
            hist = [h / total for h in hist]
        instruction_count = float(len(insns))
        indeg = float(in_degree.get(bb_addr, 0))
        outdeg = float(out_degree.get(bb_addr, 0))
        if self.feature_mode == "minimal":
            # Match fast-training schema from dataset_loader.
            return [instruction_count, indeg, outdeg, instruction_count]

        structural = [
            instruction_count,
            indeg,
            outdeg,
            float(call_count),
            float(branch_count),
            float(loop_depths.get(bb_addr, 0)),
        ]
        return hist + structural

    @staticmethod
    def _estimate_loop_depths(
        blocks: List[int],
        edges: List[Tuple[int, int]],
    ) -> Dict[int, int]:
        adjacency: Dict[int, List[int]] = {bb: [] for bb in blocks}
        reverse_adjacency: Dict[int, List[int]] = {bb: [] for bb in blocks}
        self_loops: Dict[int, bool] = {bb: False for bb in blocks}

        for src, dst in edges:
            if src not in adjacency or dst not in adjacency:
                continue
            adjacency[src].append(dst)
            reverse_adjacency[dst].append(src)
            if src == dst:
                self_loops[src] = True

        visited = set()
        order: List[int] = []

        def dfs(node: int) -> None:
            visited.add(node)
            for nxt in adjacency[node]:
                if nxt not in visited:
                    dfs(nxt)
            order.append(node)

        for bb in blocks:
            if bb not in visited:
                dfs(bb)

        visited.clear()
        components: List[List[int]] = []

        def reverse_dfs(node: int, acc: List[int]) -> None:
            visited.add(node)
            acc.append(node)
            for prev in reverse_adjacency[node]:
                if prev not in visited:
                    reverse_dfs(prev, acc)

        for bb in reversed(order):
            if bb in visited:
                continue
            component: List[int] = []
            reverse_dfs(bb, component)
            components.append(component)

        depths = {bb: 0 for bb in blocks}
        for component in components:
            if len(component) > 1:
                for bb in component:
                    depths[bb] += 1
            elif component and self_loops.get(component[0], False):
                depths[component[0]] += 1

        return depths

    def _run_gnn(self, func_addr: int, data, blocks: List[int]) -> Dict[str, Any]:
        with torch.no_grad():
            data = data.to(self.device)
            node_emb, graph_emb = self.model(data.x, data.edge_index)
            node_emb_list = node_emb.cpu().numpy().tolist()
            graph_emb_list = graph_emb.squeeze(0).cpu().numpy().tolist()
        graph_emb_bytes = json.dumps(graph_emb_list).encode("utf-8")
        graph_emb_b64 = base64.b64encode(graph_emb_bytes).decode("ascii")
        return {
            "func_addr": func_addr,
            "node_embeddings": node_emb_list,
            "graph_embedding": graph_emb_list,
            "graph_embedding_b64": graph_emb_b64,
            "block_addrs": blocks,
            "node_count": len(blocks),
            "edge_count": data.edge_index.size(1),
        }

    def _fallback_embedding(self, func_addr: int, data, blocks: List[int],
                            edges: List[Tuple[int, int]]) -> Dict[str, Any]:
        if isinstance(data, dict):
            features = data["x"]
        else:
            features = data.x.numpy().tolist() if _TORCH_AVAILABLE else data["x"]
        if features:
            dim = len(features[0])
            pooled = [0.0] * dim
            for feat in features:
                for i in range(dim):
                    pooled[i] += feat[i]
            pooled = [v / len(features) for v in pooled]
        else:
            pooled = [0.0] * self._node_feature_dim
        graph_emb = (pooled + [0.0] * self.embedding_dim)[: self.embedding_dim]
        graph_emb_bytes = json.dumps(graph_emb).encode("utf-8")
        graph_emb_b64 = base64.b64encode(graph_emb_bytes).decode("ascii")
        node_embeddings = [
            (feat + [0.0] * self.embedding_dim)[: self.embedding_dim]
            for feat in features
        ] if features else []
        return {
            "func_addr": func_addr,
            "node_embeddings": node_embeddings,
            "graph_embedding": graph_emb,
            "graph_embedding_b64": graph_emb_b64,
            "block_addrs": blocks,
            "node_count": len(blocks),
            "edge_count": len(edges),
        }

    def _empty_result(self, func_addr: int) -> Dict[str, Any]:
        empty_vec = [0.0] * self.embedding_dim
        return {
            "func_addr": func_addr,
            "node_embeddings": [],
            "graph_embedding": empty_vec,
            "graph_embedding_b64": base64.b64encode(
                json.dumps(empty_vec).encode("utf-8")
            ).decode("ascii"),
            "block_addrs": [],
            "node_count": 0,
            "edge_count": 0,
        }
