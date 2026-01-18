#!/usr/bin/env python3
"""
Offline graph builder: Pre-builds the street network with safety scoring
and saves it as a pickle file for fast loading on the server.

Run this locally once, then deploy the .pkl file with web_app.py.
"""

import pickle
import time
from config import BBOX
from graph_builder import build_safe_graph

# Attributes to keep for routing and visualization
KEEP_ATTRS = {
    'geometry',           # For rendering and route geometry
    'length',             # For distance/travel_time calculations
    'travel_time',        # For routing weight
    'safety_score',       # For safety visualization
    'light_count',        # For debug visualization
    'curve_score',        # For component breakdown
    'darkness_score',     # For component breakdown
    'highway_risk',       # For component breakdown
    'highway_tag',        # For road type display
    'land_risk',          # For component breakdown
    'land_label',         # For component breakdown
    'speed_kph',          # For reference
    'name',               # For street name
    'optimized_weight',   # For routing (safety-adjusted)
}

def strip_graph(G):
    """Remove unnecessary attributes from graph to reduce serialization size.
    
    Args:
        G: NetworkX MultiDiGraph with full edge attributes
    
    Returns:
        Stripped graph with only essential attributes
    """
    print(f"Stripping graph to essential attributes...")
    attrs_before = set()
    for u, v, k, data in G.edges(keys=True, data=True):
        attrs_before.update(data.keys())
        break
    
    print(f"  Attributes before: {sorted(attrs_before)}")
    
    # Remove attributes we don't need
    for u, v, k, data in G.edges(keys=True, data=True):
        keys_to_remove = [key for key in data.keys() if key not in KEEP_ATTRS]
        for key in keys_to_remove:
            del data[key]
    
    attrs_after = set()
    for u, v, k, data in G.edges(keys=True, data=True):
        attrs_after.update(data.keys())
        break
    
    print(f"  Attributes after: {sorted(attrs_after)}")
    print(f"  Removed {len(attrs_before) - len(attrs_after)} attributes per edge")
    
    return G


def estimate_size(obj):
    """Rough estimate of serialized size in MB."""
    try:
        data = pickle.dumps(obj)
        return len(data) / 1024 / 1024
    except Exception as e:
        print(f"  Could not estimate size: {e}")
        return 0


if __name__ == '__main__':
    print(f"Building graph offline for BBOX={BBOX}...")
    print()
    
    # Build the full graph with all scoring
    print("[1] Building graph with build_safe_graph()...")
    start = time.time()
    G, lights = build_safe_graph(BBOX)
    elapsed = time.time() - start
    print(f"    Done in {elapsed:.2f}s")
    print(f"    Nodes: {len(G.nodes())}")
    print(f"    Edges: {len(G.edges())}")
    print(f"    Lights: {len(lights) if lights else 0}")
    print()
    
    # Strip to minimal attributes
    print("[2] Stripping graph to essential attributes...")
    G = strip_graph(G)
    print()
    
    # Estimate and save
    print("[3] Estimating serialized size...")
    est_size = estimate_size(G)
    print(f"    Estimated size: {est_size:.2f} MB")
    print()
    
    # Save graph to pickle
    output_file = 'graph_prebuilt.pkl'
    print(f"[4] Saving to {output_file}...")
    with open(output_file, 'wb') as f:
        pickle.dump((G, lights, BBOX), f)
    print(f"    Done!")
    print()
    
    # Verify by loading
    print("[5] Verifying by loading...")
    with open(output_file, 'rb') as f:
        G_loaded, lights_loaded, bbox_loaded = pickle.load(f)
    print(f"    Loaded: nodes={len(G_loaded.nodes())} edges={len(G_loaded.edges())} lights={len(lights_loaded) if lights_loaded else 0}")
    print(f"    BBOX matches: {bbox_loaded == BBOX}")
    print()
    
    print("✓ Offline build complete!")
    print(f"  Next step: Deploy {output_file} with web_app.py")
