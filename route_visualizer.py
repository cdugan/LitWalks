"""
Route Visualizer: Compare fastest vs safest driving routes.

Takes start and end addresses (or coordinates), computes two routes:
  - Fastest: optimizes for travel time
  - Safest: optimizes for safety (lights + low curvature)
  
Visualizes both routes on a safety-colored map.
"""

import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors as mcolors
from matplotlib.lines import Line2D
from graph_builder import build_safe_graph
from config import BBOX

try:
    from geopy.geocoders import Nominatim
    HAS_GEOPY = True
except ImportError:
    HAS_GEOPY = False
    print("Warning: geopy not installed. Use 'pip install geopy' to enable address geocoding.")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def geocode_address(address):
    """Convert an address string to (lat, lon) coordinates using Nominatim.
    
    Tries the full address first, then progressively simpler versions if needed.
    """
    if not HAS_GEOPY:
        raise ImportError("geopy is required for address geocoding. Install with: pip install geopy")
    
    geolocator = Nominatim(user_agent="litroutes_visualizer")
    
    # Try progressively simpler versions of the address
    address_variants = [
        address,  # Full address
        address.split(',')[0] + ',' + ','.join(address.split(',')[1:]),  # Original
    ]
    
    # Add variants without ZIP code
    if ',' in address:
        parts = [p.strip() for p in address.split(',')]
        # Try without ZIP code (last part if it looks like a ZIP)
        if len(parts) > 1 and any(c.isdigit() for c in parts[-1]):
            address_variants.append(', '.join(parts[:-1]))
        # Try just street and city
        if len(parts) >= 2:
            address_variants.append(f"{parts[0]}, {parts[-2]}")
        # Try just city and state
        if len(parts) >= 2:
            address_variants.append(', '.join(parts[-2:]))
    
    for variant in address_variants:
        try:
            location = geolocator.geocode(variant, timeout=10)
            if location:
                print(f"  ✓ '{address}' -> ({location.latitude}, {location.longitude})")
                return location.latitude, location.longitude
        except Exception:
            continue
    
    # If all variants failed, provide helpful error message
    raise ValueError(
        f"Could not geocode address: '{address}'. "
        f"Try using a simpler format like 'Street, City, State' or just 'City, State'. "
        f"You can also use coordinates directly as a tuple: (lat, lon)"
    )


def snap_to_nearest_node(G, lat, lon):
    """Find the nearest graph node to (lat, lon)."""
    import osmnx as ox
    nearest_node = ox.nearest_nodes(G, X=lon, Y=lat)
    return nearest_node


def get_osrm_route(lat1, lon1, lat2, lon2):
    """Get route from OSRM API (public server or self-hosted).
    
    Returns list of (lat, lon) coordinates along the route.
    Uses public OSRM server by default.
    """
    if not HAS_REQUESTS:
        return None
    
    try:
        # OSRM public server (may have rate limits)
        url = f"https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?geometries=geojson"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get('code') == 'Ok' and data.get('routes'):
            # Extract coordinates from GeoJSON geometry
            coords = data['routes'][0]['geometry']['coordinates']
            route = [(lat, lon) for lon, lat in coords]  # Swap from GeoJSON (lon, lat) to (lat, lon)
            distance = data['routes'][0]['distance']  # meters
            duration = data['routes'][0]['duration']  # seconds
            return route, distance, duration
        else:
            print(f"  ⚠️ OSRM error: {data.get('message', 'Unknown error')}")
            return None
    except Exception as e:
        print(f"  ⚠️ OSRM API error: {e}")
        return None


def snap_osrm_route_to_graph(G, route_coords):
    """Snap OSRM route coordinates to nearest graph nodes."""
    import osmnx as ox
    
    if not route_coords or len(route_coords) < 2:
        return None
    
    # Snap first and last coordinates
    start_node = ox.nearest_nodes(G, X=route_coords[0][1], Y=route_coords[0][0])
    end_node = ox.nearest_nodes(G, X=route_coords[-1][1], Y=route_coords[-1][0])
    
    # Try to snap intermediate points to find the actual path in the graph
    try:
        # For now, compute a path in the graph between start and end
        # A more sophisticated approach would snap all intermediate points
        path = nx.shortest_path(G, start_node, end_node, weight='travel_time')
        return path
    except nx.NetworkXNoPath:
        return None

# FYI I Think this is unused
def compare_routes(bbox, start_input, end_input):
    """
    Compute and visualize fastest vs safest routes between two points.
    
    Args:
        bbox: (north, south, east, west) for the road network area.
        start_input: Starting address (string) or coordinates (tuple of (lat, lon)).
        end_input: Ending address (string) or coordinates (tuple of (lat, lon)).
    """
    # Convert addresses to coordinates if needed
    if isinstance(start_input, str):
        print(f"Geocoding start address: '{start_input}'...")
        start_lat, start_lon = geocode_address(start_input)
    else:
        start_lat, start_lon = start_input
    
    if isinstance(end_input, str):
        print(f"Geocoding end address: '{end_input}'...")
        end_lat, end_lon = geocode_address(end_input)
    else:
        end_lat, end_lon = end_input
    
    # Validate that start/end are within the bounding box
    north, south, east, west = bbox
    if not (south <= start_lat <= north and west <= start_lon <= east):
        print(f"⚠️  WARNING: Start ({start_lat}, {start_lon}) is outside bbox {bbox}")
    if not (south <= end_lat <= north and west <= end_lon <= east):
        print(f"⚠️  WARNING: End ({end_lat}, {end_lon}) is outside bbox {bbox}")
    
    print(f"Building safe graph for {bbox}...")
    G, lights = build_safe_graph(bbox)
    
    print(f"Snapping start ({start_lat}, {start_lon}) and end ({end_lat}, {end_lon}) to nearest nodes...")
    start_node = snap_to_nearest_node(G, start_lat, start_lon)
    end_node = snap_to_nearest_node(G, end_lat, end_lon)
    
    print(f"  Start node: {start_node}, End node: {end_node}")
    
    # Compute fastest route (use OSRM for real-world routing)
    print("Computing fastest route using OSRM...")
    osrm_result = get_osrm_route(start_lat, start_lon, end_lat, end_lon)
    
    if osrm_result:
        route_coords, osrm_distance, osrm_duration = osrm_result
        print(f"  ✓ OSRM route: {osrm_distance:.0f}m, {osrm_duration:.1f}s, avg speed {osrm_distance / osrm_duration * 3.6:.1f} km/h")
        
        # Snap the OSRM route to the graph
        fastest_route = snap_osrm_route_to_graph(G, route_coords)
        
        if fastest_route:
            fastest_time = sum(
                G.edges[fastest_route[i], fastest_route[i+1], 0].get('travel_time', 0)
                for i in range(len(fastest_route) - 1)
            )
            fastest_distance = sum(
                G.edges[fastest_route[i], fastest_route[i+1], 0].get('length', 0)
                for i in range(len(fastest_route) - 1)
            )
            fastest_speed_avg = (fastest_distance / fastest_time * 3.6) if fastest_time > 0 else 0
            print(f"  Fastest route: {len(fastest_route)} nodes, {fastest_time:.1f} sec, {fastest_distance:.0f}m, avg speed {fastest_speed_avg:.1f} km/h")
        else:
            print("  ⚠️ Could not snap OSRM route to graph, falling back to networkx...")
            fastest_route = None
    else:
        fastest_route = None
    
    # Fallback to networkx if OSRM fails
    if fastest_route is None:
        print("Computing fastest route using NetworkX (fallback)...")
        try:
            fastest_route = nx.shortest_path(G, start_node, end_node, weight='travel_time')
            fastest_time = sum(
                G.edges[fastest_route[i], fastest_route[i+1], 0].get('travel_time', 0)
                for i in range(len(fastest_route) - 1)
            )
            fastest_distance = sum(
                G.edges[fastest_route[i], fastest_route[i+1], 0].get('length', 0)
                for i in range(len(fastest_route) - 1)
            )
            fastest_speed_avg = (fastest_distance / fastest_time * 3.6) if fastest_time > 0 else 0
            print(f"  Fastest route (NetworkX): {len(fastest_route)} nodes, {fastest_time:.1f} sec, {fastest_distance:.0f}m, avg speed {fastest_speed_avg:.1f} km/h")
        except nx.NetworkXNoPath:
            print("  ⚠️ No path found for fastest route!")
            fastest_route = None
            fastest_time = None
    
    # Compute safest route (minimize optimized_weight, which combines time and safety)
    print("Computing safest route...")
    try:
        safest_route = nx.shortest_path(G, start_node, end_node, weight='optimized_weight')
        safest_time = sum(
            G.edges[safest_route[i], safest_route[i+1], 0].get('travel_time', 0)
            for i in range(len(safest_route) - 1)
        )
        safest_safety = sum(
            G.edges[safest_route[i], safest_route[i+1], 0].get('safety_score', 100)
            for i in range(len(safest_route) - 1)
        )
        print(f"  Safest route: {len(safest_route)} nodes, {safest_time:.1f} seconds, safety={safest_safety:.1f}")
    except nx.NetworkXNoPath:
        print("  ⚠️ No path found for safest route!")
        safest_route = None
        safest_time = None
    
    # Visualization
    print("Creating visualization...")
    fig, (ax_map, ax_routes) = plt.subplots(1, 2, figsize=(32, 12), facecolor='#222222')
    ax_map.set_facecolor('#222222')
    ax_routes.set_facecolor('#222222')
    
    # Color all edges by safety_score
    import osmnx as ox
    scores = [data.get('safety_score', 100) for u, v, k, data in G.edges(keys=True, data=True)]
    if scores:
        norm = mcolors.Normalize(vmin=min(scores), vmax=max(scores))
    else:
        norm = mcolors.Normalize(vmin=0, vmax=150)
    cmap = cm.get_cmap('coolwarm')
    edge_colors = [cmap(norm(s)) for s in scores]
    
    # --- LEFT PLOT: Map only (no routes) ---
    ox.plot_graph(G, ax=ax_map, edge_color=edge_colors, edge_linewidth=1.0,
                  bgcolor='#222222', node_size=0, show=False)
    
    # Add street labels to map plot
    major_highway_types = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary'}
    labeled_streets = set()
    label_count = 0
    
    for u, v, k, data in G.edges(keys=True, data=True):
        highway_type = data.get('highway', '')
        if isinstance(highway_type, list):
            highway_type = highway_type[0]
        
        street_name = data.get('name', '')
        if isinstance(street_name, list):
            street_name = street_name[0]
        
        if (street_name and highway_type in major_highway_types and 
            street_name not in labeled_streets and label_count < 30):
            x_mid = (G.nodes[u]['x'] + G.nodes[v]['x']) / 2
            y_mid = (G.nodes[u]['y'] + G.nodes[v]['y']) / 2
            
            ax_map.text(x_mid, y_mid, street_name, fontsize=8, color='#00FFFF',
                    alpha=0.9, ha='center', va='center', weight='bold',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='#000000', alpha=0.7, edgecolor='#00FFFF', linewidth=0.5))
            labeled_streets.add(street_name)
            label_count += 1
    
    # Overlay Duke lights on map plot
    if lights:
        lats, lons = zip(*lights)
        ax_map.scatter(lons, lats, c='#FFFF00', s=3, edgecolors='none',
                   zorder=5, alpha=0.5, label='Duke Streetlights')
    
    # Overlay start and end on map plot
    ax_map.scatter([start_lon], [start_lat], c='#00FF00', s=150, marker='o',
               edgecolors='white', linewidths=2, zorder=11, label='Start', alpha=0.95)
    ax_map.scatter([start_lon], [start_lat], c='none', s=200, marker='o',
               edgecolors='#00FF00', linewidths=1.5, zorder=10, alpha=0.5)
    
    ax_map.scatter([end_lon], [end_lat], c='#FF0000', s=150, marker='s',
               edgecolors='white', linewidths=2, zorder=11, label='End', alpha=0.95)
    ax_map.scatter([end_lon], [end_lat], c='none', s=200, marker='s',
               edgecolors='#FF0000', linewidths=1.5, zorder=10, alpha=0.5)
    
    ax_map.legend(loc='upper left', fontsize=10, facecolor='#333333', edgecolor='white',
              labelcolor='white', framealpha=0.9)
    ax_map.set_title('Safety Map (No Routes)', color='white', fontsize=12, pad=20)
    ax_map.tick_params(colors='white')
    for spine in ax_map.spines.values():
        spine.set_color('white')
    
    # --- RIGHT PLOT: Map with routes ---
    ox.plot_graph(G, ax=ax_routes, edge_color=edge_colors, edge_linewidth=1.0,
                  bgcolor='#222222', node_size=0, show=False)
    
    # Add street labels to routes plot
    labeled_streets = set()
    label_count = 0
    
    for u, v, k, data in G.edges(keys=True, data=True):
        highway_type = data.get('highway', '')
        if isinstance(highway_type, list):
            highway_type = highway_type[0]
        
        street_name = data.get('name', '')
        if isinstance(street_name, list):
            street_name = street_name[0]
        
        if (street_name and highway_type in major_highway_types and 
            street_name not in labeled_streets and label_count < 30):
            x_mid = (G.nodes[u]['x'] + G.nodes[v]['x']) / 2
            y_mid = (G.nodes[u]['y'] + G.nodes[v]['y']) / 2
            
            ax_routes.text(x_mid, y_mid, street_name, fontsize=8, color='#00FFFF',
                    alpha=0.9, ha='center', va='center', weight='bold',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='#000000', alpha=0.7, edgecolor='#00FFFF', linewidth=0.5))
            labeled_streets.add(street_name)
            label_count += 1
    
    # Overlay Duke lights on routes plot
    if lights:
        lats, lons = zip(*lights)
        ax_routes.scatter(lons, lats, c='#FFFF00', s=3, edgecolors='none',
                   zorder=5, alpha=0.5, label='Duke Streetlights')
    
    # Overlay start and end on routes plot
    ax_routes.scatter([start_lon], [start_lat], c='#00FF00', s=150, marker='o',
               edgecolors='white', linewidths=2, zorder=11, label='Start', alpha=0.95)
    ax_routes.scatter([start_lon], [start_lat], c='none', s=200, marker='o',
               edgecolors='#00FF00', linewidths=1.5, zorder=10, alpha=0.5)
    
    ax_routes.scatter([end_lon], [end_lat], c='#FF0000', s=150, marker='s',
               edgecolors='white', linewidths=2, zorder=11, label='End', alpha=0.95)
    ax_routes.scatter([end_lon], [end_lat], c='none', s=200, marker='s',
               edgecolors='#FF0000', linewidths=1.5, zorder=10, alpha=0.5)
    
    # Overlay fastest route
    if fastest_route and len(fastest_route) > 1:
        route_lats = [G.nodes[n]['y'] for n in fastest_route]
        route_lons = [G.nodes[n]['x'] for n in fastest_route]
        ax_routes.plot(route_lons, route_lats, color='#00CCFF', linewidth=3, zorder=8,
                label=f'Fastest ({fastest_time:.0f}s)', alpha=0.9)
    
    # Overlay safest route
    if safest_route and len(safest_route) > 1:
        route_lats = [G.nodes[n]['y'] for n in safest_route]
        route_lons = [G.nodes[n]['x'] for n in safest_route]
        ax_routes.plot(route_lons, route_lats, color='#00FF00', linewidth=3, zorder=8,
                label=f'Safest ({safest_time:.0f}s)', alpha=0.8, linestyle='--')
    
    # Add colorbar for safety scores
    from matplotlib.cm import ScalarMappable
    sm = ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=[ax_map, ax_routes], fraction=0.02, pad=0.02)
    cbar.set_label('Safety Score (lower=safer)', color='white', fontsize=11)
    cbar.ax.yaxis.set_tick_params(color='white', labelcolor='white')
    
    # Legend and title for routes plot
    ax_routes.legend(loc='upper left', fontsize=10, facecolor='#333333', edgecolor='white',
              labelcolor='white', framealpha=0.9)
    ax_routes.set_title('Route Comparison: Fastest (cyan) vs Safest (green)', color='white', fontsize=12, pad=20)
    ax_routes.tick_params(colors='white')
    for spine in ax_routes.spines.values():
        spine.set_color('white')
    
    plt.tight_layout()
    plt.show()
    
    return {
        'fastest': {'route': fastest_route, 'time': fastest_time},
        'safest': {'route': safest_route, 'time': safest_time}
    }
