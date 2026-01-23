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
import networkx as nx
from datetime import datetime
from zoneinfo import ZoneInfo
from route_visualizer import (
    geocode_address, snap_to_nearest_node, get_osrm_route, 
    snap_osrm_route_to_graph
)

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

# --- Pre-built graph loading ---
_GRAPH_PREBUILT_FILE = 'graph_prebuilt.pkl'
_graph_cache = {}
_businesses_cache = None
_GRAPH_LOADED = False
_GRAPH_LOAD_ERROR = None

def _load_prebuilt_graph():
    """Load the pre-built graph from pickle file."""
    global _GRAPH_LOADED, _GRAPH_LOAD_ERROR, _businesses_cache
    import pickle
    
    if not os.path.exists(_GRAPH_PREBUILT_FILE):
        _GRAPH_LOAD_ERROR = f"Pre-built graph file not found: {_GRAPH_PREBUILT_FILE}"
        print(f"[startup] ERROR: {_GRAPH_LOAD_ERROR}")
        print(f"[startup] Run 'python build_graph_offline.py' to generate it first.")
        return False
    
    try:
        print(f"[startup] Loading pre-built graph from {_GRAPH_PREBUILT_FILE}...")
        start = time.time()
        with open(_GRAPH_PREBUILT_FILE, 'rb') as f:
            data = pickle.load(f)
            # Handle both old and new pickle formats
            if len(data) == 4:
                G, lights, businesses, bbox = data
                _businesses_cache = businesses
            else:
                G, lights, bbox = data
                _businesses_cache = []
        elapsed = time.time() - start
        
        _graph_cache[str(BBOX)] = (G, lights)
        _GRAPH_LOADED = True
        print(f"[startup] Graph loaded in {elapsed:.3f}s — nodes={len(G.nodes())} edges={len(G.edges())} lights={len(lights) if lights else 0} businesses={len(_businesses_cache) if _businesses_cache else 0}")
        return True
    except Exception as e:
        _GRAPH_LOAD_ERROR = str(e)
        print(f"[startup] ERROR loading graph: {e}")
        return False

# Load graph immediately at import time (works for gunicorn workers too)
_mem_before_graph = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
print(f"[startup] Memory before loading graph: {_mem_before_graph:.1f} MB")
_load_prebuilt_graph()
_mem_after_graph_load = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
print(f"[startup] Memory after loading graph: {_mem_after_graph_load:.1f} MB (D +{_mem_after_graph_load - _mem_before_graph:.1f} MB)")

# --- GeoJSON response caching (deterministic output from fixed graph) ---
_geojson_cache = {}  # Keys: 'graph-data', 'graph-data-lite'; Values: (geojson_dict, size_bytes)


def _get_graph():
    """Return the pre-loaded graph and lights; error if missing."""
    if not _GRAPH_LOADED:
        raise RuntimeError(f"Graph not loaded. Pre-built graph file missing or load failed: {_GRAPH_LOAD_ERROR}")
    bbox_key = str(BBOX)
    if bbox_key in _graph_cache:
        return _graph_cache[bbox_key]
    raise RuntimeError("Graph cache miss despite successful load (should not happen)")


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
    G, lights = _get_graph()
    edges_fc = graph_to_geojson(G)
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
    G, lights = _get_graph()
    total_edges = len(list(G.edges(keys=True)))
    sample_interval = max(1, total_edges // 1000)
    features = []
    i = 0
    for u, v, k, data in G.edges(keys=True, data=True):
        if (i % sample_interval) != 0:
            i += 1
            continue
        geom = data.get('geometry')
        if geom is not None:
            try:
                coords = [[round(float(x), 5), round(float(y), 5)] for x, y in geom.coords]
            except Exception:
                coords = [[round(G.nodes[u]['x'], 5), round(G.nodes[u]['y'], 5)], [round(G.nodes[v]['x'], 5), round(G.nodes[v]['y'], 5)]]
        else:
            coords = [[round(G.nodes[u]['x'], 5), round(G.nodes[u]['y'], 5)], [round(G.nodes[v]['x'], 5), round(G.nodes[v]['y'], 5)]]

        length_val = data.get('length', 0)
        safety_val = data.get('safety_score', 100)

        features.append({
            'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': coords},
            'properties': {
                'safety_score': safety_val,
                'light_count': data.get('light_count', 0),
                'curve_score': data.get('curve_score', 0),
                'darkness_score': data.get('darkness_score', 0),
                'highway_risk': data.get('highway_risk', 1),
                'highway_tag': data.get('highway_tag', None),
                'land_risk': data.get('land_risk', 0.6),
                'land_label': data.get('land_label', 'Unknown')
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
        G, _ = _get_graph()
        try:
            u, v = next(iter(G.edges()))
        except StopIteration:
            print("[startup] Route warm-up skipped: graph has no edges")
            return

        # Run a lightweight nearest-node lookup to warm osmnx/shapely
        try:
            snap_to_nearest_node(G, G.nodes[u]['y'], G.nodes[u]['x'])
        except Exception as warm_err:
            print(f"[startup] Route warm-up nearest-node skipped: {warm_err}")

        # Run a quick shortest-path to warm NetworkX internals
        try:
            path = nx.shortest_path(
                G,
                u,
                v,
                weight=lambda _u, _v, data: data.get('travel_time', data.get('length', 1))
            )
            route_to_geojson(path, G, "warm")
            print(f"[startup] Route warm-up complete: {len(path)} nodes")
        except Exception as warm_path_err:
            print(f"[startup] Route warm-up path skipped: {warm_path_err}")
    except Exception as e:
        print(f"[startup] Route warm-up failed: {e}")


def graph_to_geojson(G):
    """Convert NetworkX graph to GeoJSON for map visualization."""
    features = []
    
    # Add edges as LineString features
    for u, v, k, data in G.edges(keys=True, data=True):
        try:
            # Prefer edge geometry when available so roads follow curves
            geom = data.get('geometry')
            if geom is not None:
                try:
                    coords = [[float(x), float(y)] for x, y in geom.coords]
                except Exception:
                    # Some geometries may be MultiLineString; fallback to node endpoints
                    u_lat, u_lon = G.nodes[u]['y'], G.nodes[u]['x']
                    v_lat, v_lon = G.nodes[v]['y'], G.nodes[v]['x']
                    coords = [[u_lon, u_lat], [v_lon, v_lat]]
            else:
                u_lat, u_lon = G.nodes[u]['y'], G.nodes[u]['x']
                v_lat, v_lon = G.nodes[v]['y'], G.nodes[v]['x']
                coords = [[u_lon, u_lat], [v_lon, v_lat]]

            length_val = data.get('length', 0)
            # Use danger_score (higher = more dangerous), fallback to inverted safety_score for old graphs
            danger_val = data.get('danger_score', 100 - data.get('safety_score', 0))

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords
                },
                "properties": {
                    "danger_score": danger_val,
                    "light_count": data.get('light_count', 0),
                    "darkness_score": data.get('darkness_score', 0),
                    "sidewalk_score": data.get('sidewalk_score', 0),
                    "business_score": data.get('business_score', 0.5),
                    "business_count": data.get('business_count', 0),
                    "business_name": data.get('business_name', None),
                    "business_hours": data.get('business_hours', []),
                    "is_footpath": data.get('is_footpath', False),
                    "highway": data.get('highway', 'unknown'),
                    "land_risk": data.get('land_risk', 0.6),
                    "land_label": data.get('land_label', 'Unknown'),
                    "speed_risk": data.get('speed_risk', 0.0),
                    "travel_time": data.get('travel_time', 0),
                    "length": length_val,
                    "speed_kph": data.get('speed_kph', 5),
                    "name": data.get('name', 'Unknown')
                }
            })
        except Exception as e:
            print(f"Error processing edge {u}-{v}: {e}")
            continue
    
    return {
        "type": "FeatureCollection",
        "features": features
    }


def route_to_geojson(route_nodes, G, route_type="fastest"):
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
        # Build route coordinates by concatenating edge geometries when available
        for i in range(len(route_nodes) - 1):
            u, v = route_nodes[i], route_nodes[i + 1]
            edge_data = G.edges[u, v, 0]
            properties["length"] += edge_data.get('length', 0)
            properties["travel_time"] += edge_data.get('travel_time', 0)
            properties["safety_score"] += edge_data.get('safety_score', 100)

            geom = edge_data.get('geometry')
            if geom is not None:
                try:
                    pts = [[float(x), float(y)] for x, y in geom.coords]
                except Exception:
                    # fallback to node coordinates
                    pts = [[G.nodes[u]['x'], G.nodes[u]['y']], [G.nodes[v]['x'], G.nodes[v]['y']]]
            else:
                pts = [[G.nodes[u]['x'], G.nodes[u]['y']], [G.nodes[v]['x'], G.nodes[v]['y']]]

            # Append points, avoiding duplicates
            if not coords:
                coords.extend(pts)
            else:
                # If last coord equals first of pts, skip it
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
    
    Response is cached since the graph is fixed.
    """
    # Return cached response if available
    if 'graph-data' in _geojson_cache:
        print('[api] /api/graph-data request received (cached)')
        cached_response, cached_size = _geojson_cache['graph-data']
        return jsonify(cached_response)
    
    try:
        t0 = time.time()
        print('[api] /api/graph-data request received (building cache)')
        G, lights = _get_graph()

        # Build response with graph edges, lights, and bbox
        edges_fc = graph_to_geojson(G)
        lights_list = [{"lat": lat, "lon": lon} for lat, lon in lights] if lights else []
        response = {
            "bbox": list(BBOX),  # (north, south, east, west)
            "edges": edges_fc,
            "lights": lights_list,
            "status": "success"
        }

        # Cache the response for future requests
        try:
            payload = json.dumps(response)
            size = len(payload)
            _geojson_cache['graph-data'] = (response, size)
        except Exception:
            size = None
        elapsed = time.time() - t0
        print(f"[api] /api/graph-data cached — edges={len(edges_fc.get('features',[]))} bytes={size} time_s={elapsed:.2f}")
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
        G, lights = _get_graph()

        # sample edges: take every Nth edge to keep payload small
        total_edges = len(list(G.edges(keys=True)))
        sample_interval = max(1, total_edges // 1000)  # aim for ~1000 edges

        features = []
        i = 0
        for u, v, k, data in G.edges(keys=True, data=True):
            if (i % sample_interval) != 0:
                i += 1
                continue
            geom = data.get('geometry')
            if geom is not None:
                try:
                    coords = [[round(float(x), 5), round(float(y), 5)] for x, y in geom.coords]
                except Exception:
                    coords = [[round(G.nodes[u]['x'], 5), round(G.nodes[u]['y'], 5)], [round(G.nodes[v]['x'], 5), round(G.nodes[v]['y'], 5)]]
            else:
                coords = [[round(G.nodes[u]['x'], 5), round(G.nodes[u]['y'], 5)], [round(G.nodes[v]['x'], 5), round(G.nodes[v]['y'], 5)]]

            length_val = data.get('length', 0)
            safety_val = data.get('safety_score', 100)

            features.append({
                'type': 'Feature',
                'geometry': {'type': 'LineString', 'coordinates': coords},
                'properties': {
                    'safety_score': safety_val,
                    'light_count': data.get('light_count', 0),
                    'curve_score': data.get('curve_score', 0),
                    'darkness_score': data.get('darkness_score', 0),
                    'highway_risk': data.get('highway_risk', 1),
                    'highway_tag': data.get('highway_tag', None),
                    'land_risk': data.get('land_risk', 0.6),
                    'land_label': data.get('land_label', 'Unknown')
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

        G, lights = _get_graph()

        # prepare a small preview of edges (no geometry), up to 50 entries
        preview = []
        max_preview = 50
        for i, (u, v, k, data) in enumerate(G.edges(keys=True, data=True)):
            if i >= max_preview:
                break
            # try to include simple ints for nodes; fallback to string if not castable
            try:
                u_id = int(u)
            except Exception:
                u_id = str(u)
            try:
                v_id = int(v)
            except Exception:
                v_id = str(v)
            preview.append({
                'u': u_id, 'v': v_id,
                'length': data.get('length', 0),
                'safety_score': data.get('safety_score', 100),
                'light_count': data.get('light_count', 0)
            })

        response = {
            'status': 'success',
            'bbox': list(BBOX),
            'nodes': len(G.nodes()),
            'edges': len(G.edges()),
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
        G, lights = _get_graph()
        
        features = []
        for u, v, k, data in G.edges(keys=True, data=True):
            # Only show sidewalks with explicit OSM tags
            has_explicit = data.get('has_explicit_sidewalk', False)
            sidewalk_score = data.get('sidewalk_score', 0.5)
            
            # Only include edges with explicit sidewalk data AND good sidewalk scores
            if has_explicit and sidewalk_score >= 0.8:
                # Get edge geometry or fallback to node coordinates
                geom = data.get('geometry')
                if geom:
                    coords = [[x, y] for x, y in geom.coords]
                else:
                    coords = [
                        [G.nodes[u]['x'], G.nodes[u]['y']],
                        [G.nodes[v]['x'], G.nodes[v]['y']]
                    ]
                
                features.append({
                    'type': 'Feature',
                    'geometry': {
                        'type': 'LineString',
                        'coordinates': coords
                    },
                    'properties': {
                        'sidewalk_score': sidewalk_score,
                        'sidewalk': data.get('sidewalk'),
                        'highway': data.get('highway')
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


def calculate_route_walking_metrics(route_nodes, G, lights, bbox):
    """Calculate walking-specific metrics for a route.
    
    Args:
        route_nodes: List of node IDs forming the route
        G: NetworkX graph
        lights: List of streetlight locations [(lat, lon), ...]
        bbox: Bounding box tuple (north, south, east, west)
    
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
                    # Handle MultiGraph edges - access edge 0
                    edge_data = G.edges[node1, node2, 0]
                    if edge_data.get('is_footpath', False):
                        footpath_segments += 1
                except:
                    pass
            
            metrics["footpath_coverage"] = round((footpath_segments / total_segments) * 100, 1)
        
        # Count nearby businesses along route segments
        nearby_businesses = 0
        for i in range(len(route_nodes) - 1):
            node1 = route_nodes[i]
            node2 = route_nodes[i + 1]
            try:
                edge_data = G.edges[node1, node2, 0]
                if 'business_score' in edge_data:
                    biz_score = edge_data['business_score']
                    if biz_score and biz_score > 0:
                        nearby_businesses += 1
            except:
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
        
        # Get graph
        G, lights = _get_graph()
        
        # Snap to nearest nodes
        print(f"Snapping ({start_lat}, {start_lon}) and ({end_lat}, {end_lon}) to graph...")
        start_node = snap_to_nearest_node(G, start_lat, start_lon)
        end_node = snap_to_nearest_node(G, end_lat, end_lon)
        
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
        
        # Helper: normalize edge data from MultiGraph (may be nested dict) to flat dict
        def normalize_edge_data(data_attr):
            """Handle both flat dict and nested MultiGraph dict formats."""
            if isinstance(data_attr, dict):
                # Check if it's nested (has integer keys like 0, 1, ...)
                first_key = next(iter(data_attr), None)
                if isinstance(first_key, int) and isinstance(data_attr.get(first_key), dict):
                    # Nested: extract first edge
                    return data_attr[first_key]
                elif 'osmid' in data_attr or 'length' in data_attr:
                    # Already flat
                    return data_attr
            return {}
        
        print("Computing fastest and safest routes...")
        try:
            # Precompute normalization factors for consistent weighting
            times = [d.get('travel_time', 0) for u, v, k, d in G.edges(keys=True, data=True)]
            lengths = [d.get('length', 1) for u, v, k, d in G.edges(keys=True, data=True)]
            safeties = [d.get('safety_score', 100) for u, v, k, d in G.edges(keys=True, data=True)]
            max_time = max(times) if times else 1.0
            max_length = max(lengths) if lengths else 1.0
            max_safety = max(safeties) if safeties else 100.0
            
            print(f"  max_time={max_time:.1f}s, max_length={max_length:.0f}m, max_safety={max_safety:.1f}")

            def fastest_weight(u, v, data_attr):
                data = normalize_edge_data(data_attr)
                t = (data.get('travel_time', 0) / max_time) if max_time > 0 else 0
                return t  # Pure time, no safety component
            
            def safest_weight(u, v, data_attr):
                data = normalize_edge_data(data_attr)
                length = data.get('length', 1)
                s_raw = data.get('safety_score', 100)
                s = (s_raw * length) / (max_safety * max_length) if (max_safety > 0 and max_length > 0) else 0
                return s  # Pure safety, no time component
            
            # Compute fastest route
            print("  Computing fastest route (pure time)...")
            try:
                fastest_route = nx.shortest_path(G, start_node, end_node, weight=fastest_weight)
                fastest_data["nodes"] = fastest_route
                fastest_data["distance_m"] = sum(
                    G.edges[fastest_route[i], fastest_route[i+1], 0].get('length', 0)
                    for i in range(len(fastest_route) - 1)
                )
                fastest_data["travel_time_s"] = sum(
                    G.edges[fastest_route[i], fastest_route[i+1], 0].get('travel_time', 0)
                    for i in range(len(fastest_route) - 1)
                )
                if fastest_data["travel_time_s"] > 0:
                    fastest_data["avg_speed_kmh"] = (fastest_data["distance_m"] / fastest_data["travel_time_s"]) * 3.6
                fastest_data["safety_score"] = sum(
                    (
                        G.edges[fastest_route[i], fastest_route[i+1], 0].get('safety_score', 100)
                        * (G.edges[fastest_route[i], fastest_route[i+1], 0].get('length', 1) / 1000.0)
                    )
                    for i in range(len(fastest_route) - 1)
                )
                print(f"  Fastest route: {len(fastest_route)} nodes, {fastest_data['travel_time_s']:.0f}s, safety_score={fastest_data['safety_score']:.1f}")
            except nx.NetworkXNoPath:
                print("  No fastest path found!")
            
            # Compute safest route
            print("  Computing safest route (pure safety)...")
            try:
                safest_route = nx.shortest_path(G, start_node, end_node, weight=safest_weight)
                safest_data["nodes"] = safest_route
                safest_data["distance_m"] = sum(
                    G.edges[safest_route[i], safest_route[i+1], 0].get('length', 0)
                    for i in range(len(safest_route) - 1)
                )
                safest_data["travel_time_s"] = sum(
                    G.edges[safest_route[i], safest_route[i+1], 0].get('travel_time', 0)
                    for i in range(len(safest_route) - 1)
                )
                safest_data["safety_score"] = sum(
                    (
                        G.edges[safest_route[i], safest_route[i+1], 0].get('safety_score', 100)
                        * (G.edges[safest_route[i], safest_route[i+1], 0].get('length', 1) / 1000.0)
                    )
                    for i in range(len(safest_route) - 1)
                )
                print(f"  Safest route: {len(safest_route)} nodes, {safest_data['travel_time_s']:.0f}s, safety_score={safest_data['safety_score']:.1f}")
            except nx.NetworkXNoPath:
                print("  No safest path found!")

        except nx.NetworkXNoPath:
            print("  No path found!")
        
        # Calculate walking metrics for both routes
        if fastest_route:
            fastest_metrics = calculate_route_walking_metrics(fastest_route, G, lights, BBOX)
            fastest_data.update(fastest_metrics)
        
        if safest_route:
            safest_metrics = calculate_route_walking_metrics(safest_route, G, lights, BBOX)
            safest_data.update(safest_metrics)
        
        # Convert routes to GeoJSON
        fastest_geojson = route_to_geojson(fastest_route, G, "fastest") if fastest_route else None
        safest_geojson = route_to_geojson(safest_route, G, "safest") if safest_route else None
        
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
        
        # Calculate graph cache stats
        graph_count = len(_graph_cache)
        total_nodes = 0
        total_edges = 0
        for G, lights in _graph_cache.values():
            total_nodes += len(G.nodes())
            total_edges += len(G.edges())
        
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
