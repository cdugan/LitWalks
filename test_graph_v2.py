"""Test the UPDATED safest_weight formula with real graph data."""

import pickle

def test_with_graph():
    """Load the prebuilt graph and test the NEW safest_weight formula"""
    
    # Load the prebuilt graph
    try:
        with open('graph_prebuilt.pkl', 'rb') as f:
            data = pickle.load(f)
            if len(data) == 4:
                G, lights, businesses, bbox = data
            else:
                G, lights, bbox = data
        print(f"✓ Loaded graph: {len(G.nodes())} nodes, {len(G.edges())} edges\n")
    except Exception as e:
        print(f"✗ Failed to load graph: {e}")
        return False
    
    # NEW weight function
    def safest_weight(u, v, edge_data):
        """NEW implementation of safest_weight"""
        length = edge_data.get('length', 1)
        danger = edge_data.get('danger_score', 50)
        sidewalk_score = edge_data.get('sidewalk_score', 0)
        is_footpath = (sidewalk_score >= 0.99)
        road_penalty = 1.0 if is_footpath else 10.0
        
        safety_score = 100.0 - danger
        return (length * road_penalty) / (safety_score + 1.0)
    
    # Find pairs of adjacent edges with high danger diff
    found_pairs = []
    for u, v, k, data in G.edges(keys=True, data=True):
        danger_uv = data.get('danger_score', 50)
        length_uv = data.get('length', 100)
        
        for v_next, w, k_next, data_next in G.out_edges(v, keys=True, data=True):
            danger_vw = data_next.get('danger_score', 50)
            length_vw = data_next.get('length', 100)
            
            danger_diff = abs(danger_uv - danger_vw)
            if danger_diff >= 30:
                found_pairs.append({
                    'edge1': (u, v, danger_uv, length_uv),
                    'edge2': (v_next, w, danger_vw, length_vw),
                    'danger_diff': danger_diff,
                })
    
    print(f"Testing with {min(10, len(found_pairs))} pairs of adjacent edges:\n")
    
    correct_count = 0
    for i, pair in enumerate(found_pairs[:10]):
        u, v, danger_uv, length_uv = pair['edge1']
        v_next, w, danger_vw, length_vw = pair['edge2']
        
        edge1_data = G.edges[u, v, 0]
        edge2_data = G.edges[v_next, w, 0]
        
        weight1 = safest_weight(u, v, edge1_data)
        weight2 = safest_weight(v_next, w, edge2_data)
        
        # Determine which is safer
        safer_idx = 2 if danger_vw < danger_uv else 1
        preferred_idx = 2 if weight2 < weight1 else 1
        
        is_correct = safer_idx == preferred_idx
        correct_count += is_correct
        status = "✓" if is_correct else "✗"
        
        print(f"{status} Pair {i+1}:")
        print(f"    Edge 1 ({u}->{v}): danger={danger_uv:.1f}, length={length_uv:.0f}m -> weight={weight1:.2f}")
        print(f"    Edge 2 ({v_next}->{w}): danger={danger_vw:.1f}, length={length_vw:.0f}m -> weight={weight2:.2f}")
        print(f"    Safer edge: Edge {safer_idx}, Preferred: Edge {preferred_idx}")
        print()
    
    print(f"Result: {correct_count}/10 pairs correct ({correct_count*10}%)")

if __name__ == '__main__':
    test_with_graph()
