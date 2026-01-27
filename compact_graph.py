import heapq
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np


@dataclass
class CompactGraph:
    node_ids: np.ndarray
    node_x: np.ndarray
    node_y: np.ndarray
    indptr: np.ndarray
    indices: np.ndarray
    edge_length: np.ndarray
    edge_travel_time: np.ndarray
    edge_danger: np.ndarray
    edge_sidewalk: np.ndarray
    edge_is_footpath: np.ndarray
    edge_business_score: np.ndarray
    edge_optimized_weight: np.ndarray
    edge_u_idx: np.ndarray
    edge_v_idx: np.ndarray
    edge_k: np.ndarray
    weights_fastest: np.ndarray
    weights_safest: np.ndarray
    node_id_to_idx: Dict

    def shortest_path(self, start_node_id, end_node_id, weight: str = "fastest") -> Tuple[Optional[List], Optional[List[int]]]:
        """Compute shortest path using Dijkstra on CSR adjacency.

        Returns:
            (route_node_ids, edge_indices) or (None, None) if no path.
        """
        start_idx = self.node_id_to_idx.get(start_node_id)
        end_idx = self.node_id_to_idx.get(end_node_id)
        if start_idx is None or end_idx is None:
            return None, None

        n = self.node_ids.shape[0]
        dist = np.full(n, np.inf, dtype=np.float64)
        prev = np.full(n, -1, dtype=np.int64)
        prev_edge = np.full(n, -1, dtype=np.int64)

        weights = self.weights_fastest if weight == "fastest" else self.weights_safest

        dist[start_idx] = 0.0
        heap = [(0.0, int(start_idx))]

        while heap:
            d, u = heapq.heappop(heap)
            if d != dist[u]:
                continue
            if u == end_idx:
                break
            start = self.indptr[u]
            end = self.indptr[u + 1]
            for edge_idx in range(start, end):
                v = int(self.indices[edge_idx])
                nd = d + float(weights[edge_idx])
                if nd < dist[v]:
                    dist[v] = nd
                    prev[v] = u
                    prev_edge[v] = edge_idx
                    heapq.heappush(heap, (nd, v))

        if prev[end_idx] == -1:
            return None, None

        # Reconstruct path
        node_indices = []
        edge_indices = []
        cur = int(end_idx)
        while cur != -1:
            node_indices.append(cur)
            edge_idx = int(prev_edge[cur])
            if edge_idx != -1:
                edge_indices.append(edge_idx)
            cur = int(prev[cur])

        node_indices.reverse()
        edge_indices.reverse()

        route_node_ids = [self.node_ids[i] for i in node_indices]
        return route_node_ids, edge_indices

    def edge_keys_for_path(self, edge_indices: List[int]) -> List[Tuple]:
        """Return list of (u, v, k) for given edge indices."""
        keys = []
        for idx in edge_indices:
            u_id = self.node_ids[int(self.edge_u_idx[idx])]
            v_id = self.node_ids[int(self.edge_v_idx[idx])]
            k = int(self.edge_k[idx])
            keys.append((u_id, v_id, k))
        return keys


def build_compact_graph(G) -> CompactGraph:
    """Build a CSR-based compact graph from a NetworkX MultiDiGraph."""
    node_ids = list(G.nodes())
    node_id_to_idx = {nid: i for i, nid in enumerate(node_ids)}

    node_x = np.array([G.nodes[n].get('x', 0.0) for n in node_ids], dtype=np.float32)
    node_y = np.array([G.nodes[n].get('y', 0.0) for n in node_ids], dtype=np.float32)

    src_idx = []
    dst_idx = []
    length_list = []
    travel_time_list = []
    danger_list = []
    sidewalk_list = []
    is_footpath_list = []
    business_score_list = []
    optimized_weight_list = []
    edge_u_idx = []
    edge_v_idx = []
    edge_k_list = []
    weights_fastest = []
    weights_safest = []

    for u, v, k, data in G.edges(keys=True, data=True):
        su = node_id_to_idx.get(u)
        sv = node_id_to_idx.get(v)
        if su is None or sv is None:
            continue

        length = float(data.get('length', 0.0) or 0.0)
        travel_time = float(data.get('travel_time', length) or 0.0)
        danger = float(data.get('danger_score', 50.0) or 0.0)
        sidewalk_score = float(data.get('sidewalk_score', 0.0) or 0.0)
        is_footpath = bool(data.get('is_footpath', sidewalk_score >= 0.99))
        business_score = float(data.get('business_score', 0.5) or 0.0)

        road_penalty = 1.0 if is_footpath else 10.0

        optimized_weight = data.get('optimized_weight', None)
        if optimized_weight is None:
            safety_for_routing = 100.0 - danger
            optimized_weight = travel_time * road_penalty / (safety_for_routing + 0.01)
        optimized_weight = float(optimized_weight)

        safest_weight = danger * length * road_penalty

        src_idx.append(su)
        dst_idx.append(sv)
        length_list.append(length)
        travel_time_list.append(travel_time)
        danger_list.append(danger)
        sidewalk_list.append(sidewalk_score)
        is_footpath_list.append(is_footpath)
        business_score_list.append(business_score)
        optimized_weight_list.append(optimized_weight)
        edge_u_idx.append(su)
        edge_v_idx.append(sv)
        edge_k_list.append(k)
        weights_fastest.append(optimized_weight)
        weights_safest.append(safest_weight)

    if not src_idx:
        empty = np.array([], dtype=np.int64)
        return CompactGraph(
            node_ids=np.array(node_ids, dtype=object),
            node_x=node_x,
            node_y=node_y,
            indptr=np.zeros(len(node_ids) + 1, dtype=np.int64),
            indices=empty,
            edge_length=np.array([], dtype=np.float32),
            edge_travel_time=np.array([], dtype=np.float32),
            edge_danger=np.array([], dtype=np.float32),
            edge_sidewalk=np.array([], dtype=np.float32),
            edge_is_footpath=np.array([], dtype=bool),
            edge_business_score=np.array([], dtype=np.float32),
            edge_optimized_weight=np.array([], dtype=np.float32),
            edge_u_idx=np.array([], dtype=np.int32),
            edge_v_idx=np.array([], dtype=np.int32),
            edge_k=np.array([], dtype=np.int32),
            weights_fastest=np.array([], dtype=np.float32),
            weights_safest=np.array([], dtype=np.float32),
            node_id_to_idx=node_id_to_idx,
        )

    src_idx = np.array(src_idx, dtype=np.int32)
    dst_idx = np.array(dst_idx, dtype=np.int32)

    order = np.argsort(src_idx, kind='stable')

    src_idx = src_idx[order]
    dst_idx = dst_idx[order]

    n = len(node_ids)
    counts = np.bincount(src_idx, minlength=n)
    indptr = np.zeros(n + 1, dtype=np.int64)
    indptr[1:] = np.cumsum(counts)

    indices = dst_idx.astype(np.int32, copy=False)

    def _reorder(arr, dtype):
        return np.array(arr, dtype=dtype)[order]

    edge_length = _reorder(length_list, np.float32)
    edge_travel_time = _reorder(travel_time_list, np.float32)
    edge_danger = _reorder(danger_list, np.float32)
    edge_sidewalk = _reorder(sidewalk_list, np.float32)
    edge_is_footpath = _reorder(is_footpath_list, bool)
    edge_business_score = _reorder(business_score_list, np.float32)
    edge_optimized_weight = _reorder(optimized_weight_list, np.float32)
    edge_u_idx = _reorder(edge_u_idx, np.int32)
    edge_v_idx = _reorder(edge_v_idx, np.int32)
    edge_k = _reorder(edge_k_list, np.int32)
    weights_fastest = _reorder(weights_fastest, np.float32)
    weights_safest = _reorder(weights_safest, np.float32)

    return CompactGraph(
        node_ids=np.array(node_ids, dtype=object),
        node_x=node_x,
        node_y=node_y,
        indptr=indptr,
        indices=indices,
        edge_length=edge_length,
        edge_travel_time=edge_travel_time,
        edge_danger=edge_danger,
        edge_sidewalk=edge_sidewalk,
        edge_is_footpath=edge_is_footpath,
        edge_business_score=edge_business_score,
        edge_optimized_weight=edge_optimized_weight,
        edge_u_idx=edge_u_idx,
        edge_v_idx=edge_v_idx,
        edge_k=edge_k,
        weights_fastest=weights_fastest,
        weights_safest=weights_safest,
        node_id_to_idx=node_id_to_idx,
    )
