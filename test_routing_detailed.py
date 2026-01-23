"""More detailed test to debug the safe routing issue."""

import pickle
import networkx as nx

def test_specific_scenario():
    """Test the exact scenario from the user: danger 44 vs danger 5"""
    
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
    
    # Weight function from web_app.py
    def safest_weight(u, v, edge_data):
        """Current implementation of safest_weight from web_app.py"""
        length = edge_data.get('length', 1)
        danger = edge_data.get('danger_score', 50)
        sidewalk_score = edge_data.get('sidewalk_score', 0)
        is_footpath = (sidewalk_score >= 0.99)
        road_penalty = 1.0 if is_footpath else 10.0
        
        safety_for_routing = 100.0 - danger
        return length * road_penalty * (danger / (safety_for_routing + 0.01))
    
    # Test case 1: Same length, different danger
    print("=== TEST 1: Adjacent roads, same length (~100m), different danger ===")
    print("Road A: danger=44, length=100m")
    print("Road B: danger=5, length=100m")
    
    weight_44 = 100 * 10 * (44 / (100.0 - 44 + 0.01))
    weight_5 = 100 * 10 * (5 / (100.0 - 5 + 0.01))
    
    print(f"Weight for Road A (danger=44): {weight_44:.2f}")
    print(f"Weight for Road B (danger=5):  {weight_5:.2f}")
    print(f"Preference: {'Road B [CORRECT]' if weight_5 < weight_44 else 'Road A [WRONG]'}\n")
    
    # Test case 2: Different lengths, different danger
    print("=== TEST 2: Adjacent roads, different length, different danger ===")
    print("Road A: danger=44, length=100m")
    print("Road B: danger=5, length=150m (slightly longer)")
    
    weight_44_100 = 100 * 10 * (44 / (100.0 - 44 + 0.01))
    weight_5_150 = 150 * 10 * (5 / (100.0 - 5 + 0.01))
    
    print(f"Weight for Road A (danger=44, len=100): {weight_44_100:.2f}")
    print(f"Weight for Road B (danger=5, len=150):  {weight_5_150:.2f}")
    print(f"Preference: {'Road B [CORRECT]' if weight_5_150 < weight_44_100 else 'Road A [WRONG]'}\n")
    
    # Test case 3: With footpaths (no road penalty)
    print("=== TEST 3: Both are footpaths (no road penalty) ===")
    print("Footpath A: danger=44, length=100m")
    print("Footpath B: danger=5, length=100m")
    
    weight_fp_44 = 100 * 1 * (44 / (100.0 - 44 + 0.01))
    weight_fp_5 = 100 * 1 * (5 / (100.0 - 5 + 0.01))
    
    print(f"Weight for Footpath A (danger=44): {weight_fp_44:.2f}")
    print(f"Weight for Footpath B (danger=5):  {weight_fp_5:.2f}")
    print(f"Preference: {'Footpath B [CORRECT]' if weight_fp_5 < weight_fp_44 else 'Footpath A [WRONG]'}\n")
    
    # Check if there are any edges with danger exactly 44 and 5
    print("=== TEST 4: Finding real edges with danger ~44 and ~5 ===")
    edges_near_44 = []
    edges_near_5 = []
    
    for u, v, k, data in G.edges(keys=True, data=True):
        danger = data.get('danger_score', 50)
        if 43 <= danger <= 45:
            edges_near_44.append((u, v, k, data, danger))
        elif 4 <= danger <= 6:
            edges_near_5.append((u, v, k, data, danger))
    
    print(f"Found {len(edges_near_44)} edges with danger ~44")
    print(f"Found {len(edges_near_5)} edges with danger ~5")
    
    if edges_near_44 and edges_near_5:
        print("\nExample edge with danger ~44:")
        u, v, k, data, danger = edges_near_44[0]
        length = data.get('length', 0)
        sidewalk = data.get('sidewalk_score', 0)
        print(f"  Edge {u}->{v}: danger={danger:.1f}, length={length:.0f}m, sidewalk={sidewalk:.2f}")
        
        print("\nExample edge with danger ~5:")
        u, v, k, data, danger = edges_near_5[0]
        length = data.get('length', 0)
        sidewalk = data.get('sidewalk_score', 0)
        print(f"  Edge {u}->{v}: danger={danger:.1f}, length={length:.0f}m, sidewalk={sidewalk:.2f}")
    
    # Analyze the formula more carefully
    print("\n=== FORMULA ANALYSIS ===")
    print("Current formula: weight = length * road_penalty * (danger / (100 - danger + 0.01))")
    print("\nWith danger increasing from 5 to 95:")
    for d in [5, 20, 44, 60, 80, 95]:
        w = 100 * 10 * (d / (100.0 - d + 0.01))
        print(f"  danger={d:2d}: weight={w:8.2f}")
    
    print("\nThis shows that higher danger = higher weight, which is CORRECT")
    print("The algorithm should prefer low-weight edges, so it SHOULD prefer safe roads")

if __name__ == '__main__':
    test_specific_scenario()
