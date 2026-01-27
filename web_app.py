"""
LitRoutes Web Application

A Flask-based web server for visualizing and comparing fastest vs safest driving routes.
Uses the existing graph_builder and route_visualizer logic adapted for web delivery.
"""

from flask import Flask, render_template, jsonify, request, g
import time
from flask_cors import CORS
import json
import os
import psutil
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
from compact_graph import build_compact_graph

try:
    from geopy.geocoders import Nominatim
    HAS_GEOPY = True
except Exception:
    HAS_GEOPY = False

try:
    import requests
    HAS_REQUESTS = True
except Exception:
    HAS_REQUESTS = False

# BBOX for default area
# BBOX for default area (centralized in config)
from config import BBOX

# Establish a baseline memory reading before we start heavy imports.
_mem_at_start = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
print(f"[startup] Memory at module import start: {_mem_at_start:.1f} MB")

_mem_after_config = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
print(f"[startup] Memory after config import: {_mem_after_config:.1f} MB (D +{_mem_after_config - _mem_at_start:.1f} MB)")

app = Flask(__name__, static_folder='web/static', template_folder='web/templates')
CORS(app)

_mem_after_flask = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
print(f"[startup] Memory after Flask/CORS: {_mem_after_flask:.1f} MB (D +{_mem_after_flask - _mem_after_config:.1f} MB)")

# --- Helper functions ---

def is_business_open_at_time(opening_hours, check_time):
    """Check if a business is open at a given time.
    
    Args:
        opening_hours: List of period dicts from Google Places API
            Each period has: {"open": {"day": 0-6, "hour": 0-23, "minute": 0-59}, 
                             "close": {"day": 0-6, "hour": 0-23, "minute": 0-59}}
        check_time: datetime object or ISO format string
    
    Returns:
        bool: True if open at check_time, False otherwise (or if hours unknown)
    """
    try:
        if not opening_hours:
            # No hours data available - assume open for backward compatibility
            return True
        
        # Ensure opening_hours is a list
        if not isinstance(opening_hours, list):
            return True
        
        # Parse check_time if it's a string
        if isinstance(check_time, str):
            try:
                check_time = datetime.fromisoformat(check_time.replace('Z', '+00:00'))
            except Exception as e:
                print(f"Warning: Could not parse time '{check_time}': {e}")
                return True
        
        # If check_time is not a datetime object at this point, assume open
        if not isinstance(check_time, datetime):
            return True
        
        # Convert UTC time to Eastern time (where the businesses are located)
        # Google Places opening hours are in the business's local timezone
        try:
            eastern_tz = ZoneInfo("America/New_York")
            if check_time.tzinfo is None:
                # If naive datetime, assume it's already in local time
                check_time_local = check_time
            else:
                # Convert from UTC to Eastern
                check_time_local = check_time.astimezone(eastern_tz)
        except Exception as e:
            print(f"Warning: Timezone conversion failed: {e}")
            check_time_local = check_time
        
        # Get day of week (0=Monday in Python, but Google uses 0=Sunday)
        check_day = (check_time_local.weekday() + 1) % 7  # Convert Python's Monday=0 to Google's Sunday=0
        check_minutes = check_time_local.hour * 60 + check_time_local.minute
        
        # Check each period to see if we're in an open window
        for period in opening_hours:
            if not isinstance(period, dict):
                continue
                
            open_info = period.get("open", {})
            close_info = period.get("close", {})
            
            if not open_info or not close_info:
                continue
                
            open_day = open_info.get("day", -1)
            open_minutes = open_info.get("hour", 0) * 60 + open_info.get("minute", 0)
            close_day = close_info.get("day", -1)
            close_minutes = close_info.get("hour", 0) * 60 + close_info.get("minute", 0)
            
            # Handle same-day hours
            if open_day == close_day == check_day:
                if open_minutes <= check_minutes < close_minutes:
                    return True
            
            # Handle hours that span midnight
            elif open_day != close_day:
                # Check if we're on the opening day after opening time
                if check_day == open_day and check_minutes >= open_minutes:
                    return True
                # Check if we're on the closing day before closing time
                elif check_day == close_day and check_minutes < close_minutes:
                    return True
        
        return False
    except Exception as e:
        print(f"Error in is_business_open_at_time: {e}")
        import traceback
        traceback.print_exc()
        # On any error, assume open to avoid breaking the app
        return True

# --- Business Score Recalculation ---

def geocode_address(address):
    """Convert an address string to (lat, lon) coordinates using Nominatim."""
    if not HAS_GEOPY:
        raise ImportError("geopy is required for address geocoding. Install with: pip install geopy")

    geolocator = Nominatim(user_agent="litwalks_web")
    address_variants = [
        address,
        address.split(',')[0] + ',' + ','.join(address.split(',')[1:]),
    ]

    if ',' in address:
        parts = [p.strip() for p in address.split(',')]
        if len(parts) > 1 and any(c.isdigit() for c in parts[-1]):
            address_variants.append(', '.join(parts[:-1]))
        if len(parts) >= 2:
            address_variants.append(f"{parts[0]}, {parts[-2]}")
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

    raise ValueError(
        f"Could not geocode address: '{address}'. "
        f"Try 'Street, City, State' or use coordinates directly."
    )


def get_osrm_route(lat1, lon1, lat2, lon2):
    """Get route from OSRM API (public server)."""
    if not HAS_REQUESTS:
        return None
    try:
        url = f"https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?geometries=geojson"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('code') == 'Ok' and data.get('routes'):
            coords = data['routes'][0]['geometry']['coordinates']
            route = [(lat, lon) for lon, lat in coords]
            distance = data['routes'][0]['distance']
            duration = data['routes'][0]['duration']
            return route, distance, duration
        print(f"  ⚠️ OSRM error: {data.get('message', 'Unknown error')}")
        return None
    except Exception as e:
        print(f"  ⚠️ OSRM API error: {e}")
        return None


def snap_to_nearest_node(compact_graph, lat, lon):
    """Find nearest node in compact graph to (lat, lon)."""
    dx = compact_graph.node_x - float(lon)
    dy = compact_graph.node_y - float(lat)
    idx = int(np.argmin(dx * dx + dy * dy))
    return compact_graph.node_ids[idx]

def _recalculate_business_scores(G, businesses, departure_time):
    """Recalculate business proximity scores based on open businesses at departure_time.
    
    This creates a modified copy of the graph with updated business_score and 
    recalculated danger_score/optimized_weight based on which businesses are open.
    
    Args:
        G: NetworkX graph with pre-calculated scores
        businesses: List of business tuples (lat, lon, name, type, hours, review_count, is_open)
        departure_time: ISO format datetime string
    
    Returns:
        Modified graph with updated scores
    """
    import copy
    from math import radians, cos, sin, asin, sqrt
    
    # Constants from graph_builder (should match)
    W_DARKNESS = 40.0
    W_SIDEWALK = 30.0
    W_BUSINESS = 15.0
    W_LAND = 10.0
    W_SPEED = 5.0
    DANGER_MULTIPLIER = 3.0
    PROXIMITY_THRESHOLD_KM = 0.1  # 100m - businesses within this radius affect safety
    
    def haversine_km(lat1, lon1, lat2, lon2):
        """Calculate distance between two points in km."""
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        return c * 6371  # Earth radius in km
    
    # Filter to only open businesses
    open_businesses = []
    for biz in businesses:
        if len(biz) >= 7:
            lat, lon, name, btype, hours, review_count, is_open = biz[:7]
            if is_business_open_at_time(hours, departure_time):
                open_businesses.append((lat, lon, name))
    
    print(f"  Open businesses at {departure_time}: {len(open_businesses)}/{len(businesses)}")
    
    # Recalculate business scores for all edges
    edges_updated = 0
    score_changes = []  # Track some score changes for debugging
    for u, v, k, data in G.edges(keys=True, data=True):
        # Store original danger score for comparison
        original_danger = data.get('danger_score', 0)
        
        # Get edge midpoint
        if 'geometry' in data and hasattr(data['geometry'], 'coords'):
            coords = list(data['geometry'].coords)
            mid_idx = len(coords) // 2
            edge_lat, edge_lon = coords[mid_idx][1], coords[mid_idx][0]  # (x, y) = (lon, lat)
        else:
            # Fallback: use node coordinates
            node_u_data = G.nodes[u]
            node_v_data = G.nodes[v]
            edge_lat = (node_u_data.get('y', 0) + node_v_data.get('y', 0)) / 2
            edge_lon = (node_u_data.get('x', 0) + node_v_data.get('x', 0)) / 2
        
        # Count open businesses within proximity threshold
        nearby_count = 0
        for biz_lat, biz_lon, biz_name in open_businesses:
            dist = haversine_km(edge_lat, edge_lon, biz_lat, biz_lon)
            if dist <= PROXIMITY_THRESHOLD_KM:
                nearby_count += 1
        
        # Calculate new business score (same logic as graph_builder)
        if nearby_count > 0:
            business_score = 0.9  # Good: near open businesses
        else:
            business_score = 0.3  # Poor: isolated area
        
        # Get other pre-calculated components
        darkness_score = data.get('darkness_score', 0.5)
        sidewalk_score = data.get('sidewalk_score', 0.5)
        land_risk = data.get('land_risk', 0.5)
        speed_risk = data.get('speed_risk', 0.5)
        travel_time = data.get('travel_time', 1)
        
        # Recalculate danger score with new business component
        danger = (
            W_DARKNESS * darkness_score +
            W_SIDEWALK * (1.0 - sidewalk_score) +
            W_BUSINESS * (1.0 - business_score) +  # Updated component
            W_LAND * land_risk +
            W_SPEED * speed_risk
        )
        
        # Recalculate optimized weight (for routing) - match graph_builder.py formula
        # Apply 10x penalty for roads vs footpaths, divide by safety (higher safety = lower weight)
        is_footpath = (sidewalk_score >= 0.99)
        road_penalty = 1.0 if is_footpath else 10.0
        safety_for_routing = 100.0 - danger
        optimized_weight = travel_time * road_penalty / (safety_for_routing + 0.01)
        
        # Update edge data
        data['business_score'] = business_score
        data['business_count'] = nearby_count
        data['danger_score'] = danger
        data['optimized_weight'] = optimized_weight
        
        # Also update safety_score (inverse of danger, used for visualization)
        data['safety_score'] = 100 - danger
        
        # Track significant changes for debugging
        if len(score_changes) < 5 and abs(danger - original_danger) > 1.0:
            score_changes.append({
                'edge': f"{u}->{v}",
                'old_danger': original_danger,
                'new_danger': danger,
                'old_biz': data.get('business_score', 0.5),
                'new_biz': business_score,
                'nearby': nearby_count
            })
        
        edges_updated += 1
    
    print(f"  Updated business scores for {edges_updated} edges")
    if score_changes:
        print(f"  Sample score changes:")
        for change in score_changes:
            print(f"    {change['edge']}: danger {change['old_danger']:.1f}->{change['new_danger']:.1f}, biz {change['old_biz']:.2f}->{change['new_biz']:.2f}, nearby={change['nearby']}")
    
    return G


def _recalculate_business_scores_compact(compact, businesses, departure_time):
    """Recalculate business proximity scores on compact graph in-place."""
    from math import radians, cos, sin, asin, sqrt

    W_DARKNESS = 40.0
    W_SIDEWALK = 30.0
    W_BUSINESS = 15.0
    W_LAND = 10.0
    W_SPEED = 5.0
    PROXIMITY_THRESHOLD_KM = 0.1

    def haversine_km(lat1, lon1, lat2, lon2):
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        return c * 6371

    open_businesses = []
    for biz in businesses:
        if len(biz) >= 7:
            lat, lon, name, btype, hours, review_count, is_open = biz[:7]
            if is_business_open_at_time(hours, departure_time):
                open_businesses.append((lat, lon, name))

    print(f"  Open businesses at {departure_time}: {len(open_businesses)}/{len(businesses)}")

    edge_count = len(compact.edge_u_idx)
    for i in range(edge_count):
        u_idx = int(compact.edge_u_idx[i])
        v_idx = int(compact.edge_v_idx[i])

        edge_lat = (float(compact.node_y[u_idx]) + float(compact.node_y[v_idx])) / 2.0
        edge_lon = (float(compact.node_x[u_idx]) + float(compact.node_x[v_idx])) / 2.0

        nearby_count = 0
        for biz_lat, biz_lon, _ in open_businesses:
            dist = haversine_km(edge_lat, edge_lon, biz_lat, biz_lon)
            if dist <= PROXIMITY_THRESHOLD_KM:
                nearby_count += 1

        business_score = 0.9 if nearby_count > 0 else 0.3

        darkness_score = float(compact.edge_darkness_score[i]) if compact.edge_darkness_score.size else 0.5
        sidewalk_score = float(compact.edge_sidewalk[i]) if compact.edge_sidewalk.size else 0.5
        land_risk = float(compact.edge_land_risk[i]) if compact.edge_land_risk.size else 0.5
        speed_risk = float(compact.edge_speed_risk[i]) if compact.edge_speed_risk.size else 0.5
        travel_time = float(compact.edge_travel_time[i]) if compact.edge_travel_time.size else 1.0
        length = float(compact.edge_length[i]) if compact.edge_length.size else 1.0

        danger = (
            W_DARKNESS * darkness_score +
            W_SIDEWALK * (1.0 - sidewalk_score) +
            W_BUSINESS * (1.0 - business_score) +
            W_LAND * land_risk +
            W_SPEED * speed_risk
        )

        is_footpath = bool(compact.edge_is_footpath[i]) if compact.edge_is_footpath.size else False
        road_penalty = 1.0 if is_footpath else 10.0
        safety_for_routing = 100.0 - danger
        optimized_weight = travel_time * road_penalty / (safety_for_routing + 0.01)
        safest_weight = danger * length * road_penalty

        if compact.edge_business_score.size:
            compact.edge_business_score[i] = business_score
        if compact.edge_business_count.size:
            compact.edge_business_count[i] = nearby_count
        if compact.edge_danger.size:
            compact.edge_danger[i] = danger
        if compact.edge_optimized_weight.size:
            compact.edge_optimized_weight[i] = optimized_weight
        if compact.weights_fastest.size:
            compact.weights_fastest[i] = optimized_weight
        if compact.weights_safest.size:
            compact.weights_safest[i] = safest_weight

    return compact

# --- Pre-built graph loading (lazy + compressed) ---
_GRAPH_PREBUILT_FILE = 'graph_prebuilt.pkl'
_GRAPH_PREBUILT_FILE_GZ = 'graph_prebuilt.pkl.gz'
_compact_graph_cache = {}
_lights_cache = {}
_businesses_cache = None
_GRAPH_LOADED = False
_GRAPH_LOAD_ERROR = None

def _load_prebuilt_graph():
    """Load the pre-built graph from pickle file (supports gzip compression)."""
    global _GRAPH_LOADED, _GRAPH_LOAD_ERROR, _businesses_cache
    import pickle
    import gzip
    
    # Try compressed file first, then uncompressed
    if os.path.exists(_GRAPH_PREBUILT_FILE_GZ):
        graph_file = _GRAPH_PREBUILT_FILE_GZ
        use_gzip = True
    elif os.path.exists(_GRAPH_PREBUILT_FILE):
        graph_file = _GRAPH_PREBUILT_FILE
        use_gzip = False
    else:
        _GRAPH_LOAD_ERROR = f"Pre-built graph file not found: {_GRAPH_PREBUILT_FILE} or {_GRAPH_PREBUILT_FILE_GZ}"
        print(f"[graph] ERROR: {_GRAPH_LOAD_ERROR}")
        print(f"[graph] Run 'python build_graph_offline.py' to generate it first.")
        return False
    
    try:
        print(f"[graph] Loading pre-built graph from {graph_file}...")
        start = time.time()
        
        if use_gzip:
            with gzip.open(graph_file, 'rb') as f:
                data = pickle.load(f)
        else:
            with open(graph_file, 'rb') as f:
                data = pickle.load(f)
        
        # Handle both old and new pickle formats
        if len(data) == 4:
            G, lights, businesses, bbox = data
            _businesses_cache = businesses
        else:
            G, lights, bbox = data
            _businesses_cache = []
        
        elapsed = time.time() - start
        _lights_cache[str(BBOX)] = lights
        try:
            compact_start = time.time()
            compact = build_compact_graph(G)
            _compact_graph_cache[str(BBOX)] = compact
            compact_elapsed = time.time() - compact_start
            print(f"[graph] Compact routing graph built in {compact_elapsed:.3f}s — nodes={len(compact.node_ids)} edges={len(compact.indices)}")
        except Exception as cg_err:
            print(f"[graph] WARNING: failed to build compact graph: {cg_err}")
        _GRAPH_LOADED = True

        # Release NetworkX graph to reduce memory footprint
        try:
            del G
        except Exception:
            pass
        
        file_size = os.path.getsize(graph_file) / (1024 * 1024)
        node_count = len(compact.node_ids) if str(BBOX) in _compact_graph_cache else 0
        edge_count = len(compact.indices) if str(BBOX) in _compact_graph_cache else 0
        print(f"[graph] Graph loaded in {elapsed:.3f}s ({file_size:.1f}MB) — nodes={node_count} edges={edge_count} lights={len(lights) if lights else 0} businesses={len(_businesses_cache) if _businesses_cache else 0}")
        return True
    except Exception as e:
        _GRAPH_LOAD_ERROR = str(e)
        print(f"[graph] ERROR loading graph: {e}")
        return False

# Don't load graph at startup - load on first request to reduce memory footprint
print(f"[startup] Graph will be loaded on first request (lazy loading enabled)")

# --- GeoJSON response caching (deterministic output from fixed graph) ---
_geojson_cache = {}  # Keys: 'graph-data', 'graph-data-lite'; Values: (geojson_dict, size_bytes)


def _get_graph():
    """Return the compact graph and lights; load on-demand if needed."""
    compact = _get_compact_graph()
    lights = _get_lights()
    return compact, lights


def _get_compact_graph():
    """Return the compact routing graph; build on-demand if missing."""
    if not _GRAPH_LOADED:
        print("[graph] Lazy loading graph on first request...")
        success = _load_prebuilt_graph()
        if not success:
            raise RuntimeError(f"Graph failed to load: {_GRAPH_LOAD_ERROR}")
    bbox_key = str(BBOX)
    if bbox_key in _compact_graph_cache:
        return _compact_graph_cache[bbox_key]
    # Fallback not possible without NetworkX graph cached
    raise RuntimeError("Compact graph cache miss despite successful load (should not happen)")


def _get_lights():
    """Return cached lights list; load on-demand if needed."""
    if not _GRAPH_LOADED:
        print("[graph] Lazy loading graph on first request...")
        success = _load_prebuilt_graph()
        if not success:
            raise RuntimeError(f"Graph failed to load: {_GRAPH_LOAD_ERROR}")
    bbox_key = str(BBOX)
    if bbox_key in _lights_cache:
        return _lights_cache[bbox_key]
    return []


def get_memory_usage():
    """Get current memory usage in MB."""
    try:
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / 1024 / 1024
    except Exception:
        return 0


@app.before_request
def log_memory_before():
    """Log memory before request."""
    try:
        g.mem_before = get_memory_usage()
    except Exception:
        g.mem_before = 0


@app.after_request
def log_memory_after(response):
    """Log memory after request and compute delta."""
    try:
        mem_after = get_memory_usage()
        mem_before = getattr(g, 'mem_before', 0)
        delta = mem_after - mem_before
        print(f"[memory] {request.method} {request.path}: {mem_after:.1f}MB (Δ {delta:+.1f}MB)")
    except Exception:
        pass
    return response


def _build_full_geojson_cache():
    """Build and cache the full graph GeoJSON (deterministic)."""
    if 'graph-data' in _geojson_cache:
        return
    compact, lights = _get_graph()
    edges_fc = graph_to_geojson(compact)
    lights_list = [{"lat": lat, "lon": lon} for lat, lon in lights] if lights else []
    response = {
        "bbox": list(BBOX),
        "edges": edges_fc,
        "lights": lights_list,
        "status": "success"
    }
    try:
        payload = json.dumps(response)
        _geojson_cache['graph-data'] = (response, len(payload))
    except Exception:
        _geojson_cache['graph-data'] = (response, None)


def _build_lite_geojson_cache():
    """Build and cache the sampled graph GeoJSON (deterministic)."""
    if 'graph-data-lite' in _geojson_cache:
        return
    compact, lights = _get_graph()
    total_edges = len(compact.edge_u_idx)
    sample_interval = max(1, total_edges // 1000)
    features = []
    i = 0
    for edge_idx in range(total_edges):
        if (i % sample_interval) != 0:
            i += 1
            continue
        start = int(compact.edge_geom_indptr[edge_idx])
        end = int(compact.edge_geom_indptr[edge_idx + 1])
        if end > start:
            coords = [[round(float(x), 5), round(float(y), 5)] for x, y in zip(compact.edge_geom_x[start:end], compact.edge_geom_y[start:end])]
        else:
            u_idx = int(compact.edge_u_idx[edge_idx])
            v_idx = int(compact.edge_v_idx[edge_idx])
            coords = [
                [round(float(compact.node_x[u_idx]), 5), round(float(compact.node_y[u_idx]), 5)],
                [round(float(compact.node_x[v_idx]), 5), round(float(compact.node_y[v_idx]), 5)]
            ]

        length_val = float(compact.edge_length[edge_idx])
        safety_val = 100.0 - float(compact.edge_danger[edge_idx])

        features.append({
            'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': coords},
            'properties': {
                'safety_score': safety_val,
                'light_count': int(compact.edge_light_count[edge_idx]) if compact.edge_light_count.size else 0,
                'curve_score': 0,
                'darkness_score': float(compact.edge_darkness_score[edge_idx]) if compact.edge_darkness_score.size else 0.0,
                'highway_risk': 1,
                'highway_tag': None,
                'land_risk': float(compact.edge_land_risk[edge_idx]) if compact.edge_land_risk.size else 0.6,
                'land_label': 'Unknown'
            }
        })
        i += 1

    response = {'status': 'success', 'edges': {'type': 'FeatureCollection', 'features': features}, 'lights': [{"lat": lat, "lon": lon} for lat, lon in lights] if lights else []}
    try:
        payload = json.dumps(response)
        _geojson_cache['graph-data-lite'] = (response, len(payload))
    except Exception:
        _geojson_cache['graph-data-lite'] = (response, None)


def _warm_geojson_caches():
    """Build both caches at startup to avoid lazy work on first request."""
    _build_full_geojson_cache()
    _build_lite_geojson_cache()


def _warm_route_computation():
    """Prime a tiny route computation so first user request is fast."""
    try:
        compact = _get_compact_graph()
        try:
            if len(compact.edge_u_idx) == 0:
                raise StopIteration
            u_idx = int(compact.edge_u_idx[0])
            v_idx = int(compact.edge_v_idx[0])
            u = compact.node_ids[u_idx]
            v = compact.node_ids[v_idx]
        except StopIteration:
            print("[startup] Route warm-up skipped: graph has no edges")
            return

        # Run a lightweight nearest-node lookup to warm osmnx/shapely
        try:
            snap_to_nearest_node(compact, compact.node_y[u_idx], compact.node_x[u_idx])
        except Exception as warm_err:
            print(f"[startup] Route warm-up nearest-node skipped: {warm_err}")

        # Run a quick shortest-path to warm routing internals
        try:
            path, edge_indices = compact.shortest_path(u, v, weight="fastest")
            if path and edge_indices:
                route_to_geojson(path, compact, "warm", edge_indices=edge_indices)
                print(f"[startup] Route warm-up complete: {len(path)} nodes")
            else:
                print("[startup] Route warm-up skipped: no path")
        except Exception as warm_path_err:
            print(f"[startup] Route warm-up path skipped: {warm_path_err}")
    except Exception as e:
        print(f"[startup] Route warm-up failed: {e}")


def graph_to_geojson(compact):
    """Convert compact graph to GeoJSON for map visualization."""
    features = []
    edge_count = len(compact.edge_u_idx)

    for i in range(edge_count):
        try:
            start = int(compact.edge_geom_indptr[i])
            end = int(compact.edge_geom_indptr[i + 1])
            if end > start:
                coords = [[float(x), float(y)] for x, y in zip(compact.edge_geom_x[start:end], compact.edge_geom_y[start:end])]
            else:
                u_idx = int(compact.edge_u_idx[i])
                v_idx = int(compact.edge_v_idx[i])
                coords = [
                    [float(compact.node_x[u_idx]), float(compact.node_y[u_idx])],
                    [float(compact.node_x[v_idx]), float(compact.node_y[v_idx])]
                ]

            length_val = float(compact.edge_length[i])
            danger_val = float(compact.edge_danger[i])

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords
                },
                "properties": {
                    "danger_score": danger_val,
                    "light_count": int(compact.edge_light_count[i]) if compact.edge_light_count.size else 0,
                    "darkness_score": float(compact.edge_darkness_score[i]) if compact.edge_darkness_score.size else 0.0,
                    "sidewalk_score": float(compact.edge_sidewalk[i]) if compact.edge_sidewalk.size else 0.0,
                    "business_score": float(compact.edge_business_score[i]) if compact.edge_business_score.size else 0.5,
                    "business_count": int(compact.edge_business_count[i]) if compact.edge_business_count.size else 0,
                    "business_name": None,
                    "business_hours": [],
                    "is_footpath": bool(compact.edge_is_footpath[i]) if compact.edge_is_footpath.size else False,
                    "highway": "unknown",
                    "land_risk": float(compact.edge_land_risk[i]) if compact.edge_land_risk.size else 0.6,
                    "land_label": "Unknown",
                    "speed_risk": float(compact.edge_speed_risk[i]) if compact.edge_speed_risk.size else 0.0,
                    "travel_time": float(compact.edge_travel_time[i]) if compact.edge_travel_time.size else 0.0,
                    "length": length_val,
                    "speed_kph": float(compact.edge_speed_kph[i]) if compact.edge_speed_kph.size else 5.0,
                    "name": "Unknown"
                }
            })
        except Exception as e:
            print(f"Error processing edge #{i}: {e}")
            continue

    return {
        "type": "FeatureCollection",
        "features": features
    }


def route_to_geojson(route_nodes, compact, route_type="fastest", edge_indices=None):
    """Convert a route (list of node IDs) to GeoJSON."""
    if not route_nodes or len(route_nodes) < 2:
        return None
    
    coords = []
    properties = {
        "type": route_type,
        "length": 0,
        "travel_time": 0,
        "safety_score": 0
    }
    
    try:
        if edge_indices is None:
            edge_indices = list(range(len(route_nodes) - 1))

        for i in range(len(route_nodes) - 1):
            u_id = route_nodes[i]
            v_id = route_nodes[i + 1]
            u_idx = compact.node_id_to_idx.get(u_id)
            v_idx = compact.node_id_to_idx.get(v_id)
            if u_idx is None or v_idx is None:
                continue

            edge_idx = edge_indices[i] if i < len(edge_indices) else None
            if edge_idx is not None:
                properties["length"] += float(compact.edge_length[edge_idx])
                properties["travel_time"] += float(compact.edge_travel_time[edge_idx])
                safety = 100.0 - float(compact.edge_danger[edge_idx])
                properties["safety_score"] += safety

                start = int(compact.edge_geom_indptr[edge_idx])
                end = int(compact.edge_geom_indptr[edge_idx + 1])
                if end > start:
                    pts = [[float(x), float(y)] for x, y in zip(compact.edge_geom_x[start:end], compact.edge_geom_y[start:end])]
                else:
                    pts = [
                        [float(compact.node_x[u_idx]), float(compact.node_y[u_idx])],
                        [float(compact.node_x[v_idx]), float(compact.node_y[v_idx])]
                    ]
            else:
                pts = [
                    [float(compact.node_x[u_idx]), float(compact.node_y[u_idx])],
                    [float(compact.node_x[v_idx]), float(compact.node_y[v_idx])]
                ]

            if not coords:
                coords.extend(pts)
            else:
                if coords[-1] == pts[0]:
                    coords.extend(pts[1:])
                else:
                    coords.extend(pts)
    except Exception as e:
        print(f"Error building route GeoJSON: {e}")
        return None
    
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": coords
        },
        "properties": properties
    }


# Warm caches at module import (no lazy loading)
_warm_geojson_caches()

# Warm a tiny route computation to avoid first-request latency
_warm_route_computation()


@app.route('/')
def index():
    """Serve the main web interface."""
    return render_template('index.html', bbox=BBOX)


@app.route('/api/graph-data', methods=['GET'])
def api_graph_data():
    """Get the road network graph as GeoJSON.
    
    Query parameters:
        departure_time: Optional ISO datetime to recalculate business scores
    
    Response is cached when no departure_time is provided.
    """
    departure_time = request.args.get('departure_time')
    
    # Return cached response if available and no departure_time
    if not departure_time and 'graph-data' in _geojson_cache:
        print('[api] /api/graph-data request received (cached)')
        cached_response, cached_size = _geojson_cache['graph-data']
        return jsonify(cached_response)
    
    try:
        t0 = time.time()
        if departure_time:
            print(f'[api] /api/graph-data request received with departure_time={departure_time}')
        else:
            print('[api] /api/graph-data request received (building cache)')
        
        compact, lights = _get_graph()
        
        # Recalculate business scores if departure_time provided
        if departure_time and _businesses_cache:
            _recalculate_business_scores_compact(compact, _businesses_cache, departure_time)

        # Build response with graph edges, lights, and bbox
        edges_fc = graph_to_geojson(compact)
        lights_list = [{"lat": lat, "lon": lon} for lat, lon in lights] if lights else []
        response = {
            "bbox": list(BBOX),  # (north, south, east, west)
            "edges": edges_fc,
            "lights": lights_list,
            "status": "success"
        }

        # Cache the response only if no departure_time
        if not departure_time:
            try:
                payload = json.dumps(response)
                size = len(payload)
                _geojson_cache['graph-data'] = (response, size)
            except Exception:
                size = None
        else:
            size = len(json.dumps(response))
            
        elapsed = time.time() - t0
        print(f"[api] /api/graph-data {'cached' if not departure_time else 'computed'} — edges={len(edges_fc.get('features',[]))} bytes={size} time_s={elapsed:.2f}")
        return jsonify(response)
    except Exception as e:
        print(f"[api] /api/graph-data error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/graph-data-lite', methods=['GET'])
def api_graph_data_lite():
    """Return a trimmed/sampled GeoJSON to allow fast client-side loading.

    This reduces coordinate precision, drops unused properties, and samples edges.
    Response is cached since the graph is fixed.
    """
    # Return cached response if available
    if 'graph-data-lite' in _geojson_cache:
        print('[api] /api/graph-data-lite request received (cached)')
        cached_response, cached_size = _geojson_cache['graph-data-lite']
        return jsonify(cached_response)
    
    try:
        print('[api] /api/graph-data-lite request received (building cache)')
        compact, lights = _get_graph()

        # sample edges: take every Nth edge to keep payload small
        total_edges = len(compact.edge_u_idx)
        sample_interval = max(1, total_edges // 1000)  # aim for ~1000 edges

        features = []
        i = 0
        for edge_idx in range(total_edges):
            if (i % sample_interval) != 0:
                i += 1
                continue
            start = int(compact.edge_geom_indptr[edge_idx])
            end = int(compact.edge_geom_indptr[edge_idx + 1])
            if end > start:
                coords = [[round(float(x), 5), round(float(y), 5)] for x, y in zip(compact.edge_geom_x[start:end], compact.edge_geom_y[start:end])]
            else:
                u_idx = int(compact.edge_u_idx[edge_idx])
                v_idx = int(compact.edge_v_idx[edge_idx])
                coords = [
                    [round(float(compact.node_x[u_idx]), 5), round(float(compact.node_y[u_idx]), 5)],
                    [round(float(compact.node_x[v_idx]), 5), round(float(compact.node_y[v_idx]), 5)]
                ]

            length_val = float(compact.edge_length[edge_idx])
            safety_val = 100.0 - float(compact.edge_danger[edge_idx])

            features.append({
                'type': 'Feature',
                'geometry': {'type': 'LineString', 'coordinates': coords},
                'properties': {
                    'safety_score': safety_val,
                    'light_count': int(compact.edge_light_count[edge_idx]) if compact.edge_light_count.size else 0,
                    'curve_score': 0,
                    'darkness_score': float(compact.edge_darkness_score[edge_idx]) if compact.edge_darkness_score.size else 0.0,
                    'highway_risk': 1,
                    'highway_tag': None,
                    'land_risk': float(compact.edge_land_risk[edge_idx]) if compact.edge_land_risk.size else 0.6,
                    'land_label': 'Unknown'
                }
            })
            i += 1

        response = {'type': 'FeatureCollection', 'features': features}
        lights_list = [{"lat": lat, "lon": lon} for lat, lon in lights] if lights else []
        full_response = {'status': 'success', 'edges': response, 'lights': lights_list}
        
        # Cache the response for future requests
        try:
            payload = json.dumps(full_response)
            _geojson_cache['graph-data-lite'] = (full_response, len(payload))
            print(f"[api] /api/graph-data-lite cached — features={len(features)} sampled_from={total_edges} size={len(payload)} bytes")
        except Exception as cache_err:
            print(f"[api] /api/graph-data-lite cache save failed: {cache_err}")
        
        return jsonify(full_response)
    except Exception as e:
        print(f"[api] /api/graph-data-lite error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/graph-summary', methods=['GET'])
def api_graph_summary():
    """Return a lightweight summary of the graph (counts and small preview).

    This is intended for quick client-side load to avoid large GeoJSON downloads.
    """
    try:
        print('[api] /api/graph-summary request received')

        compact, lights = _get_graph()

        # prepare a small preview of edges (no geometry), up to 50 entries
        preview = []
        max_preview = 50
        for i in range(len(compact.edge_u_idx)):
            if i >= max_preview:
                break
            # try to include simple ints for nodes; fallback to string if not castable
            try:
                u_id = int(compact.node_ids[int(compact.edge_u_idx[i])])
            except Exception:
                u_id = str(compact.node_ids[int(compact.edge_u_idx[i])])
            try:
                v_id = int(compact.node_ids[int(compact.edge_v_idx[i])])
            except Exception:
                v_id = str(compact.node_ids[int(compact.edge_v_idx[i])])
            preview.append({
                'u': u_id, 'v': v_id,
                'length': float(compact.edge_length[i]),
                'safety_score': 100.0 - float(compact.edge_danger[i]),
                'light_count': int(compact.edge_light_count[i]) if compact.edge_light_count.size else 0
            })

        response = {
            'status': 'success',
            'bbox': list(BBOX),
            'nodes': len(compact.node_ids),
            'edges': len(compact.edge_u_idx),
            'lights': len(lights) if lights else 0,
            'preview_edges': preview
        }
        print(f"[api] /api/graph-summary ready — nodes={response['nodes']} edges={response['edges']} lights={response['lights']}")
        return jsonify(response)
    except Exception as e:
        print(f"[api] /api/graph-summary error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/sidewalks', methods=['GET'])
def api_sidewalks():
    """Return GeoJSON of streets with explicit sidewalk data from OSM."""
    try:
        compact, _ = _get_graph()

        features = []
        for i in range(len(compact.edge_u_idx)):
            has_explicit = bool(compact.edge_has_explicit_sidewalk[i]) if compact.edge_has_explicit_sidewalk.size else False
            sidewalk_score = float(compact.edge_sidewalk[i]) if compact.edge_sidewalk.size else 0.0

            if has_explicit and sidewalk_score >= 0.8:
                u_idx = int(compact.edge_u_idx[i])
                v_idx = int(compact.edge_v_idx[i])
                coords = [
                    [float(compact.node_x[u_idx]), float(compact.node_y[u_idx])],
                    [float(compact.node_x[v_idx]), float(compact.node_y[v_idx])]
                ]

                features.append({
                    'type': 'Feature',
                    'geometry': {
                        'type': 'LineString',
                        'coordinates': coords
                    },
                    'properties': {
                        'sidewalk_score': sidewalk_score,
                        'sidewalk': None,
                        'highway': None
                    }
                })
        
        return jsonify({
            'type': 'FeatureCollection',
            'features': features
        })
    except Exception as e:
        print(f"Error fetching sidewalks: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/businesses', methods=['GET'])
def api_businesses():
    """Return list of individual business points, optionally filtered by opening hours."""
    try:
        global _businesses_cache
        
        # Get optional departure_time parameter
        departure_time = request.args.get('departure_time')
        
        # Return businesses as simple list of dicts
        business_list = []
        if _businesses_cache:
            for biz in _businesses_cache:
                # Handle both old (lat, lon, name, btype) and new (lat, lon, name, btype, hours, review_count, is_open) formats
                if len(biz) >= 4:
                    lat, lon, name, btype = biz[:4]
                    hours = biz[4] if len(biz) > 4 else []
                    review_count = biz[5] if len(biz) > 5 else 0
                    is_open = biz[6] if len(biz) > 6 else True
                    
                    # Filter by departure_time if provided
                    if departure_time:
                        if not is_business_open_at_time(hours, departure_time):
                            continue  # Skip closed businesses
                    
                    business_list.append({
                        'lat': lat,
                        'lon': lon,
                        'name': name,
                        'type': btype,
                        'hours': hours if isinstance(hours, list) else [],
                        'review_count': review_count,
                        'is_open': is_open
                    })
        
        return jsonify(business_list)
    except Exception as e:
        print(f"Error fetching businesses: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


def calculate_route_walking_metrics(route_nodes, G, lights, bbox, compact_graph=None, edge_indices=None):
    """Calculate walking-specific metrics for a route.
    
    Args:
        route_nodes: List of node IDs forming the route
        G: NetworkX graph (optional if compact_graph provided)
        lights: List of streetlight locations [(lat, lon), ...]
        bbox: Bounding box tuple (north, south, east, west)
        compact_graph: CompactGraph instance for fast metrics
        edge_indices: List of edge indices aligned to the route
    
    Returns:
        Dict with lighting_score, footpath_coverage, nearby_businesses
    """
    metrics = {
        "lighting_score": None,
        "footpath_coverage": None,
        "nearby_businesses": None
    }
    
    if not route_nodes or len(route_nodes) < 2:
        return metrics
    
    try:
        # Calculate lighting score (percentage of segments with nearby streetlights)
        lit_segments = 0
        total_segments = len(route_nodes) - 1
        
        if total_segments > 0:
            for i in range(len(route_nodes) - 1):
                node1 = route_nodes[i]
                node2 = route_nodes[i + 1]

                # Get node coordinates
                if compact_graph is not None:
                    idx1 = compact_graph.node_id_to_idx.get(node1)
                    idx2 = compact_graph.node_id_to_idx.get(node2)
                    if idx1 is None or idx2 is None:
                        continue
                    lat1, lon1 = compact_graph.node_y[idx1], compact_graph.node_x[idx1]
                    lat2, lon2 = compact_graph.node_y[idx2], compact_graph.node_x[idx2]
                else:
                    lat1, lon1 = G.nodes[node1]['y'], G.nodes[node1]['x']
                    lat2, lon2 = G.nodes[node2]['y'], G.nodes[node2]['x']
                
                # Check if any streetlights are near this segment (within ~100 meters)
                segment_midpoint_lat = (lat1 + lat2) / 2
                segment_midpoint_lon = (lon1 + lon2) / 2
                
                has_light = False
                for light_lat, light_lon in lights:
                    # Simple distance check (~0.001 degrees ≈ 111 meters)
                    dist = ((light_lat - segment_midpoint_lat) ** 2 + (light_lon - segment_midpoint_lon) ** 2) ** 0.5
                    if dist < 0.001:  # ~111 meters
                        has_light = True
                        break
                
                if has_light:
                    lit_segments += 1
            
            metrics["lighting_score"] = round((lit_segments / total_segments) * 100, 1)
        
        # Calculate footpath coverage (from edge data)
        footpath_segments = 0
        if total_segments > 0:
            for i in range(len(route_nodes) - 1):
                node1 = route_nodes[i]
                node2 = route_nodes[i + 1]

                try:
                    if compact_graph is not None and edge_indices is not None:
                        edge_idx = edge_indices[i]
                        if compact_graph.edge_is_footpath[edge_idx]:
                            footpath_segments += 1
                    else:
                        # Handle MultiGraph edges - access edge 0
                        edge_data = G.edges[node1, node2, 0]
                        if edge_data.get('is_footpath', False):
                            footpath_segments += 1
                except Exception:
                    pass
            
            metrics["footpath_coverage"] = round((footpath_segments / total_segments) * 100, 1)
        
        # Count nearby businesses along route segments
        nearby_businesses = 0
        for i in range(len(route_nodes) - 1):
            node1 = route_nodes[i]
            node2 = route_nodes[i + 1]
            try:
                if compact_graph is not None and edge_indices is not None:
                    edge_idx = edge_indices[i]
                    biz_score = compact_graph.edge_business_score[edge_idx]
                    if biz_score and biz_score > 0:
                        nearby_businesses += 1
                else:
                    edge_data = G.edges[node1, node2, 0]
                    if 'business_score' in edge_data:
                        biz_score = edge_data['business_score']
                        if biz_score and biz_score > 0:
                            nearby_businesses += 1
            except Exception:
                pass
        
        metrics["nearby_businesses"] = nearby_businesses
        
    except Exception as e:
        print(f"Warning: Could not calculate walking metrics: {e}")
        import traceback
        traceback.print_exc()
    
    return metrics


@app.route('/api/routes', methods=['POST'])
def api_routes():
    """Compute and return safest walking routes.
    
    For walking routes, we primarily return the safest route with features like:

    - Streetlight coverage
    - Sidewalk availability  
    - Proximity to open businesses
    - Land use characteristics
    """
    try:
        # Dependencies are eagerly imported at module load
        
        data = request.get_json()
        start_input = data.get('start')
        end_input = data.get('end')
        departure_time = data.get('departure_time')  # ISO format datetime for business hours
        
        if not start_input or not end_input:
            return jsonify({"status": "error", "message": "Missing start or end location"}), 400
        
        # Helper function to check if coordinates are within bounds
        def is_within_bounds(lat, lon):
            north, south, east, west = BBOX
            return south <= lat <= north and west <= lon <= east
        
        # Parse coordinates if they're provided as [lat, lon]
        if isinstance(start_input, list) and len(start_input) == 2:
            start_lat, start_lon = start_input
        elif isinstance(start_input, str):
            print(f"Geocoding start: {start_input}")
            start_lat, start_lon = geocode_address(start_input)
        else:
            return jsonify({"status": "error", "message": "Invalid start format"}), 400
        
        # Validate start coordinates are within bounds
        if not is_within_bounds(start_lat, start_lon):
            return jsonify({
                "status": "error", 
                "message": f"Start location ({start_lat:.4f}, {start_lon:.4f}) is outside the service area. Please select a location within bounds."
            }), 400
        
        if isinstance(end_input, list) and len(end_input) == 2:
            end_lat, end_lon = end_input
        elif isinstance(end_input, str):
            print(f"Geocoding end: {end_input}")
            end_lat, end_lon = geocode_address(end_input)
        else:
            return jsonify({"status": "error", "message": "Invalid end format"}), 400
        
        # Validate end coordinates are within bounds
        if not is_within_bounds(end_lat, end_lon):
            return jsonify({
                "status": "error", 
                "message": f"End location ({end_lat:.4f}, {end_lon:.4f}) is outside the service area. Please select a location within bounds."
            }), 400
        
        # Get compact graph + lights
        compact, lights = _get_graph()
        
        # If departure_time is provided, recalculate business proximity scores
        # based on which businesses are actually open at that time
        if departure_time and _businesses_cache:
            print(f"  Recalculating business scores for departure_time: {departure_time}")
            _recalculate_business_scores_compact(compact, _businesses_cache, departure_time)
        
        # Snap to nearest nodes
        print(f"Snapping ({start_lat}, {start_lon}) and ({end_lat}, {end_lon}) to graph...")
        start_node = snap_to_nearest_node(compact, start_lat, start_lon)
        end_node = snap_to_nearest_node(compact, end_lat, end_lon)
        
        print(f"Start node: {start_node}, End node: {end_node}")
        
        # Initialize data structures for two routes
        fastest_route = None
        fastest_data = {
            "nodes": [],
            "distance_m": 0,
            "travel_time_s": 0,
            "avg_speed_kmh": 0,
            "safety_score": 0,
            "lighting_score": None,
            "footpath_coverage": None,
            "nearby_businesses": None
        }
        
        safest_route = None
        safest_data = {
            "nodes": [],
            "distance_m": 0,
            "travel_time_s": 0,
            "safety_score": 0,
            "lighting_score": None,
            "footpath_coverage": None,
            "nearby_businesses": None
        }
        
        print("Computing fastest and safest routes (compact graph)...")
        try:
            # Compute fastest route
            print("  Computing fastest route (compact)...")
            fastest_route, fastest_edge_indices = compact.shortest_path(start_node, end_node, weight="fastest")
            if fastest_route and fastest_edge_indices:
                fastest_data["nodes"] = fastest_route
                edge_idx = np.array(fastest_edge_indices, dtype=np.int64)
                fastest_data["distance_m"] = float(compact.edge_length[edge_idx].sum())
                fastest_data["travel_time_s"] = float(compact.edge_travel_time[edge_idx].sum())
                if fastest_data["travel_time_s"] > 0:
                    fastest_data["avg_speed_kmh"] = (fastest_data["distance_m"] / fastest_data["travel_time_s"]) * 3.6
                safety = 100.0 - compact.edge_danger[edge_idx]
                fastest_data["safety_score"] = float((safety * (compact.edge_length[edge_idx] / 1000.0)).sum())
                print(f"  Fastest route: {len(fastest_route)} nodes, {fastest_data['travel_time_s']:.0f}s, safety_score={fastest_data['safety_score']:.1f}")
            else:
                fastest_edge_indices = None
                print("  No fastest path found!")

            # Compute safest route
            print("  Computing safest route (compact)...")
            safest_route, safest_edge_indices = compact.shortest_path(start_node, end_node, weight="safest")
            if safest_route and safest_edge_indices:
                safest_data["nodes"] = safest_route
                edge_idx = np.array(safest_edge_indices, dtype=np.int64)
                safest_data["distance_m"] = float(compact.edge_length[edge_idx].sum())
                safest_data["travel_time_s"] = float(compact.edge_travel_time[edge_idx].sum())
                safety = 100.0 - compact.edge_danger[edge_idx]
                safest_data["safety_score"] = float((safety * (compact.edge_length[edge_idx] / 1000.0)).sum())
                print(f"  Safest route: {len(safest_route)} nodes, {safest_data['travel_time_s']:.0f}s, safety_score={safest_data['safety_score']:.1f}")
            else:
                safest_edge_indices = None
                print("  No safest path found!")
        except Exception as route_err:
            fastest_edge_indices = None
            safest_edge_indices = None
            print(f"  Routing error: {route_err}")
        
        # Calculate walking metrics for both routes
        if fastest_route:
            fastest_metrics = calculate_route_walking_metrics(
                fastest_route, None, lights, BBOX, compact_graph=compact, edge_indices=fastest_edge_indices
            )
            fastest_data.update(fastest_metrics)
        
        if safest_route:
            safest_metrics = calculate_route_walking_metrics(
                safest_route, None, lights, BBOX, compact_graph=compact, edge_indices=safest_edge_indices
            )
            safest_data.update(safest_metrics)
        
        # Convert routes to GeoJSON
        fastest_geojson = None
        safest_geojson = None
        if fastest_route and fastest_edge_indices:
            fastest_geojson = route_to_geojson(fastest_route, compact, "fastest", edge_indices=fastest_edge_indices)
        if safest_route and safest_edge_indices:
            safest_geojson = route_to_geojson(safest_route, compact, "safest", edge_indices=safest_edge_indices)
        
        print(f"  fastest_route nodes: {len(fastest_route) if fastest_route else 0}, geojson: {fastest_geojson is not None}")
        print(f"  safest_route nodes: {len(safest_route) if safest_route else 0}, geojson: {safest_geojson is not None}")
        
        response = {
            "status": "success",
            "start": {"lat": start_lat, "lon": start_lon},
            "end": {"lat": end_lat, "lon": end_lon},
            "fastest": {
                "geojson": fastest_geojson,
                "data": fastest_data
            },
            "safest": {
                "geojson": safest_geojson,
                "data": safest_data
            }
        }
        
        return jsonify(response)
    
    except Exception as e:
        print(f"Error computing routes: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/memory', methods=['GET'])
def api_memory():
    """Monitor memory usage of this process and graph cache statistics."""
    try:
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        
        # Calculate compact graph cache stats
        graph_count = len(_compact_graph_cache)
        total_nodes = 0
        total_edges = 0
        for compact in _compact_graph_cache.values():
            total_nodes += len(compact.node_ids)
            total_edges += len(compact.edge_u_idx)
        
        return jsonify({
            "rss_mb": round(mem_info.rss / 1024 / 1024, 2),        # Resident Set Size (actual RAM)
            "vms_mb": round(mem_info.vms / 1024 / 1024, 2),        # Virtual Memory Size
            "percent": round(process.memory_percent(), 2),          # % of system RAM
            "graph_cache_entries": graph_count,
            "graph_total_nodes": total_nodes,
            "graph_total_edges": total_edges,
            "status": "ok"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    # Create web directories if they don't exist
    os.makedirs('web/templates', exist_ok=True)
    os.makedirs('web/static', exist_ok=True)

    # Run the development server
    print("Starting LitRoutes Web App...")
    print("Open http://localhost:5000 in your browser")
    # Disable the reloader to avoid watchdog restarts closing connections during development
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5000)
