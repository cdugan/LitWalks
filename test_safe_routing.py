"""Test script to verify safe routing prioritizes safer paths."""

import pickle
import networkx as nx
from config import BBOX

def test_safe_routing():
    """Load the prebuilt graph and test if safe routing works correctly."""
    
    # Load the prebuilt graph
    try:
        with open('graph_prebuilt.pkl', 'rb') as f:
            data = pickle.load(f)
            if len(data) == 4:
                G, lights, businesses, bbox = data
            else:
                G, lights, bbox = data
        print(f"✓ Loaded graph: {len(G.nodes())} nodes, {len(G.edges())} edges")
    except Exception as e:
        print(f"✗ Failed to load graph: {e}")
        return False
    
    # Find edges with varying danger levels
    print("\n--- Scanning for edges with different danger levels ---")
    edges_by_danger = {}
    for u, v, k, data in G.edges(keys=True, data=True):
        danger = data.get('danger_score', 50)
        length = data.get('length', 100)
        sidewalk = data.get('sidewalk_score', 0.5)
        
        # Round danger to buckets
        danger_bucket = int(danger / 10) * 10
        if danger_bucket not in edges_by_danger:
            edges_by_danger[danger_bucket] = []
        edges_by_danger[danger_bucket].append((u, v, k, data, danger, length, sidewalk))
    
    # Print distribution
    print("\nDanger score distribution:")
    for bucket in sorted(edges_by_danger.keys()):
        count = len(edges_by_danger[bucket])
        print(f"  {bucket:3d}-{bucket+9:3d}: {count:5d} edges")
    
    # Find adjacent pairs with very different danger levels
    print("\n--- Looking for adjacent edges with danger difference >= 30 ---")
    found_pairs = []
    
    for u, v, k, data in G.edges(keys=True, data=True):
        danger_uv = data.get('danger_score', 50)
        length_uv = data.get('length', 100)
        
        # Check edges that start from v
        for v_next, w, k_next, data_next in G.out_edges(v, keys=True, data=True):
            danger_vw = data_next.get('danger_score', 50)
            length_vw = data_next.get('length', 100)
            
            danger_diff = abs(danger_uv - danger_vw)
            if danger_diff >= 30:  # At least 30 point difference
                found_pairs.append({
                    'edge1': (u, v, danger_uv, length_uv),
                    'edge2': (v, w, danger_vw, length_vw),
                    'danger_diff': danger_diff,
                    'safer_edge': (v, w) if danger_vw < danger_uv else (u, v),
                })
    
    print(f"Found {len(found_pairs)} pairs of adjacent edges with danger_diff >= 30")
    
    if not found_pairs:
        print("  (No suitable adjacent pairs found)")
    else:
        # Show first 10
        print("\nFirst 10 pairs:")
        for i, pair in enumerate(found_pairs[:10]):
            e1 = pair['edge1']
            e2 = pair['edge2']
            print(f"\n  Pair {i+1}:")
            print(f"    Edge 1: {e1[0]}->{e1[1]}, danger={e1[2]:.1f}, length={e1[3]:.0f}m")
            print(f"    Edge 2: {e2[0]}->{e2[1]}, danger={e2[2]:.1f}, length={e2[3]:.0f}m")
            print(f"    Safer: Edge 2" if e2[2] < e1[2] else "    Safer: Edge 1")
            print(f"    Danger difference: {pair['danger_diff']:.1f}")
    
    # Now test the weight functions directly
    print("\n--- Testing weight functions ---")
    
    def safest_weight(u, v, edge_data):
        """Current implementation of safest_weight from web_app.py"""
        length = edge_data.get('length', 1)
        danger = edge_data.get('danger_score', 50)
        sidewalk_score = edge_data.get('sidewalk_score', 0)
        is_footpath = (sidewalk_score >= 0.99)
        road_penalty = 1.0 if is_footpath else 10.0
        
        safety_for_routing = 100.0 - danger
        return length * road_penalty * (danger / (safety_for_routing + 0.01))
    
    # Test with the first few pairs
    print("\nWeight function test (lower weight = preferred):")
    for i, pair in enumerate(found_pairs[:5]):
        u, v, danger_uv, length_uv = pair['edge1']
        v_next, w, danger_vw, length_vw = pair['edge2']
        
        # Get actual edge data
        edge1_data = G.edges[u, v, 0]
        edge2_data = G.edges[v_next, w, 0]
        
        weight1 = safest_weight(u, v, edge1_data)
        weight2 = safest_weight(v_next, w, edge2_data)
        
        safer = "CORRECT" if (weight2 < weight1 and danger_vw < danger_uv) or (weight1 < weight2 and danger_uv < danger_vw) else "WRONG"
        
        print(f"\n  Pair {i+1}:")
        print(f"    Edge {u}->{v}: danger={danger_uv:.1f}, length={length_uv:.0f}m -> weight={weight1:.2f}")
        print(f"    Edge {v_next}->{w}: danger={danger_vw:.1f}, length={length_vw:.0f}m -> weight={weight2:.2f}")
        print(f"    Prefers: {'Edge 2' if weight2 < weight1 else 'Edge 1'} [{safer}]")

if __name__ == '__main__':
    test_safe_routing()
