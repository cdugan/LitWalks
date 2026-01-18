import psutil
import os

# Memory tracking helper (define early so we can use it during imports)
def _get_mem_mb():
    """Get current process memory in MB."""
    try:
        return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    except Exception:
        return 0

from data_fetcher import fetch_duke_lights, fetch_nlcd_raster, fetch_sidewalk_coverage, fetch_open_businesses

import math
_mem_after_math = _get_mem_mb()
print(f"[graph_builder import] After math: {_mem_after_math:.1f} MB")

from config import BBOX

try:
    import geopandas as gpd
    from shapely.geometry import Point
    HAS_GPD = True
except Exception:
    HAS_GPD = False

# --- GLOBAL INPUTS ---
# BBOX is defined in config.py and imported above

# --- SAFETY SCORING PARAMS FOR WALKING ROUTES ---
# For walking, we prioritize: darkness, sidewalk availability, proximity to open businesses, and land use
# safety = w_darkness*darkness_score + w_sidewalk*sidewalk_score + w_business*business_score + w_land*land_risk
# Curviness is removed as it's not relevant for pedestrians choosing between routes
W_DARKNESS = 40.0
W_SIDEWALK = 30.0  # Higher weight for sidewalk availability (critical for walking safety)
W_BUSINESS = 15.0  # Routes near open businesses feel safer
W_LAND = 15.0
DENSITY_SCALE = 50.0  # scaling factor for lights per meter to darkness score


def get_pedestrian_street_type_score(highway_value):
    """Return pedestrian friendliness score 0..1 based on OSM highway tag (higher = more pedestrian friendly).

    For walking routes, we care more about pedestrian infrastructure than road hierarchy.
    """
    pedestrian_friendly = {
        "footway": 1.0,      # Dedicated pedestrian path
        "path": 0.95,        # General path, usually pedestrian-safe
        "residential": 0.85, # Residential streets are pedestrian-friendly
        "living_street": 0.9, # Living streets prioritize pedestrians
        "unclassified": 0.7, # Small local roads
        "tertiary": 0.6,     # Small roads
        "secondary": 0.4,    # Larger roads, less pedestrian-friendly
        "primary": 0.2,      # Major roads, higher traffic
        "trunk": 0.1,        # Very high traffic
        "motorway": 0.0,     # Not for pedestrians
    }
    
    if highway_value is None:
        return 0.5  # Unknown, neutral score
    
    def normalize_tag(t):
        try:
            tag = str(t).lower()
        except Exception:
            return None
        if tag.endswith('_link'):
            tag = tag[:-5]
        return tag
    
    # If multiple tags, choose the most pedestrian-friendly
    if isinstance(highway_value, (list, tuple, set)):
        best_score = 0.5
        for t in highway_value:
            base = normalize_tag(t)
            score = pedestrian_friendly.get(base, 0.5)
            if score > best_score:
                best_score = score
        return best_score
    
    base = normalize_tag(highway_value)
    return pedestrian_friendly.get(base, 0.5)


# WMS PNG palette index → NLCD class code mapping (for NLCD_2021_Land_Cover_L48)
# These indices are typical for the MRLC paletted PNG output
PALETTE_TO_NLCD = {
    0: 0,    # No data / background
    1: 11,   # Open Water
    2: 12,   # Perennial Ice/Snow
    3: 21,   # Developed, Open Space
    4: 22,   # Developed, Low Intensity
    5: 23,   # Developed, Medium Intensity
    6: 24,   # Developed, High Intensity
    7: 31,   # Barren Land
    8: 41,   # Deciduous Forest
    9: 42,   # Evergreen Forest
    10: 43,  # Mixed Forest
    11: 52,  # Shrub/Scrub
    12: 71,  # Grassland/Herbaceous
    13: 81,  # Pasture/Hay
    14: 82,  # Cultivated Crops
    15: 90,  # Woody Wetlands
    16: 95,  # Emergent Herbaceous Wetlands
}


def sample_nlcd_code(lon, lat, raster, bounds):
    """Sample NLCD code from raster (numpy array) given lon/lat and bounds (minx,miny,maxx,maxy)."""
    if raster is None or bounds is None:
        return None
    minx, miny, maxx, maxy = bounds
    if lon < minx or lon > maxx or lat < miny or lat > maxy:
        return None
    h, w = raster.shape[:2]
    x_frac = (lon - minx) / (maxx - minx) if maxx != minx else 0.0
    y_frac = (maxy - lat) / (maxy - miny) if maxy != miny else 0.0
    x_pix = int(x_frac * (w - 1))
    y_pix = int(y_frac * (h - 1))
    if x_pix < 0 or x_pix >= w or y_pix < 0 or y_pix >= h:
        return None
    try:
        val = raster[y_pix, x_pix]
        # Handle paletted (P) or single band: val is scalar
        if isinstance(val, (list, tuple)):
            val = val[0]
        elif hasattr(val, "shape") and len(getattr(val, "shape", [])) > 0:
            # e.g., RGB -> take first channel
            try:
                val = val[0]
            except Exception:
                pass
        palette_idx = int(val)
        # Map palette index to NLCD class code
        nlcd_code = PALETTE_TO_NLCD.get(palette_idx, None)
        return nlcd_code
    except Exception:
        return None


# NLCD land use risk mapping (higher = more dangerous)
def land_risk_from_nlcd(code):
    """Return (risk, label) given NLCD code."""
    label_lookup = {
        11: "Open Water",
        12: "Snow/Ice",
        21: "Developed Open",
        22: "Developed Low",
        23: "Developed Medium",
        24: "Developed High",
        31: "Barren",
        41: "Deciduous Forest",
        42: "Evergreen Forest",
        43: "Mixed Forest",
        52: "Shrub/Scrub",
        71: "Grassland",
        81: "Pasture/Hay",
        82: "Cultivated Crops",
        90: "Woody Wetlands",
        95: "Emergent Wetlands",
    }
    try:
        c = int(code)
    except Exception:
        return 0.6, "Unknown"

    label = label_lookup.get(c, "Unknown")

    # Risk tiers: forest/wetlands highest, ag/grass/shrub mid, urban/water lowest
    if c in {41, 42, 43, 90, 95}:  # forests & wetlands
        risk = 1.0
    elif c in {52, 71, 81, 82, 31, 21}:  # shrub/grass/ag/barren
        risk = 0.6
    elif c in {22, 23, 24, 11, 12}:  # developed & water/ice
        risk = 0.2
    else:
        risk = 0.6  # unknown mid-level
    return risk, label


def get_sinuosity(u, v, G):
    """Return sinuosity ratio for edge (u, v) on graph G.

    Assumes G is projected (metric units) so lengths make sense.
    """
    x1, y1 = G.nodes[u]['x'], G.nodes[u]['y']
    x2, y2 = G.nodes[v]['x'], G.nodes[v]['y']
    euclidean = math.hypot(x2 - x1, y2 - y1)
    if euclidean < 1:
        return 1.0
    try:
        actual = G.edges[u, v, 0].get('length', euclidean)
    except Exception:
        return 1.0
    if actual <= 0:
        return 1.0
    return actual / euclidean


def build_safe_graph(bbox):
    """Build a road graph for bbox and score edges using Duke lights + curvature.

    Returns (G_latlon, lights) where G_latlon has safety attributes and is in EPSG:4326.
    """
    # Lazy-load osmnx only when building a graph (not at app startup)
    from osmnx import graph_from_bbox, project_graph, add_edge_speeds, add_edge_travel_times
    
    mem_start = _get_mem_mb()
    print(f"In build_safe_graph... [mem: {mem_start:.1f} MB]")
    north, south, east, west = bbox
    print(f"1. Downloading street network for {bbox}...")

    # osmnx expects a tuple containing (west, south, east, north)
    G = graph_from_bbox((west, south, east, north), network_type='drive', simplify=True)
    mem_after_osm = _get_mem_mb()
    print(f"   ✓ OSM graph downloaded: {len(G.nodes())} nodes, {len(G.edges())} edges [mem: {mem_after_osm:.1f} MB, Δ +{mem_after_osm - mem_start:.1f} MB]")

    # Fetch Duke lights (list of (lat, lon))
    lights_latlon = fetch_duke_lights(bbox)
    mem_after_lights = _get_mem_mb()
    print(f"   ✓ Duke lights fetched: {len(lights_latlon) if lights_latlon else 0} lights [mem: {mem_after_lights:.1f} MB, Δ +{mem_after_lights - mem_after_osm:.1f} MB]")

    # Project graph early to avoid scikit-learn requirement when searching
    print("   Projecting graph for spatial operations...")
    G_proj = project_graph(G)
    mem_after_proj = _get_mem_mb()
    print(f"   ✓ Graph projected [mem: {mem_after_proj:.1f} MB, Δ +{mem_after_proj - mem_after_lights:.1f} MB]")

    # Initialize light counts on projected edges
    for u, v, k, data in G_proj.edges(keys=True, data=True):
        data['light_count'] = 0

    # Count lights for edges using proximity (within 15 meters)
    if lights_latlon:
        print(f"   Counting {len(lights_latlon)} Duke lights within 15m of edges (multi-edge attribution)...")
        LIGHT_PROXIMITY_THRESHOLD_M = 15.0  # Only count lights within 15 meters

        # Use a single STRtree path so each light can contribute to all nearby edges
        try:
            from shapely.geometry import Point as ShapelyPoint, LineString as ShapelyLineString
            from shapely.strtree import STRtree
            from shapely.wkb import dumps as wkb_dumps
            from pyproj import Transformer

            target_crs = G_proj.graph.get('crs') if isinstance(G_proj.graph, dict) else None
            transformer = Transformer.from_crs('EPSG:4326', target_crs, always_xy=True) if target_crs else None
            if target_crs:
                print(f"   ▶ Using CRS {target_crs} for proximity; units are in projected CRS")
            else:
                print("   ⚠️  No CRS found on projected graph; distances may be in degrees")

            edge_keys = []
            edge_geoms = []
            id_to_key = {}
            wkb_to_key = {}
            for u, v, k, data in G_proj.edges(keys=True, data=True):
                geom = data.get('geometry')
                # Ensure we have a Shapely geometry; convert if needed
                if geom is None:
                    u_node = G_proj.nodes[u]
                    v_node = G_proj.nodes[v]
                    geom = ShapelyLineString([(u_node['x'], u_node['y']), (v_node['x'], v_node['y'])])
                elif not hasattr(geom, 'geom_type'):
                    # Attempt to coerce to Shapely geometry
                    from shapely.geometry import shape as shapely_shape
                    geom = shapely_shape(geom)
                edge_keys.append((u, v, k))
                edge_geoms.append(geom)
                id_to_key[id(geom)] = (u, v, k)
                try:
                    wkb_to_key[wkb_dumps(geom)] = (u, v, k)
                except Exception:
                    # If serialization fails, we still have the id-based fallback
                    pass

            tree = STRtree(edge_geoms)
            counts = {key: 0 for key in edge_keys}

            # Quick diagnostic: sample a few lights to see min distance to any edge
            try:
                sample_lights = lights_latlon[:50]
                min_dists = []
                for lat, lon in sample_lights:
                    if transformer:
                        x, y = transformer.transform(lon, lat)
                        light_pt = ShapelyPoint(x, y)
                    else:
                        light_pt = ShapelyPoint(lon, lat)
                    nearest_geom = tree.nearest(light_pt)
                    if nearest_geom is not None:
                        # Shapely may return either a geometry or an index depending on version
                        if not hasattr(nearest_geom, 'geom_type'):
                            try:
                                nearest_geom = edge_geoms[int(nearest_geom)]
                            except Exception:
                                nearest_geom = None
                        if nearest_geom is not None and hasattr(nearest_geom, 'geom_type'):
                            try:
                                min_dists.append(light_pt.distance(nearest_geom))
                            except Exception:
                                continue
                if min_dists:
                    print(f"   ▶ Min/median/mean distance of sample lights to edges: {min(min_dists):.2f} / {sorted(min_dists)[len(min_dists)//2]:.2f} / {(sum(min_dists)/len(min_dists)):.2f} (CRS units)")
            except Exception as diag_err:
                print(f"   ⚠️  Distance diagnostic failed: {diag_err}")

            for lat, lon in lights_latlon:
                if transformer:
                    x, y = transformer.transform(lon, lat)
                    light_pt = ShapelyPoint(x, y)
                else:
                    light_pt = ShapelyPoint(lon, lat)
                buf = light_pt.buffer(LIGHT_PROXIMITY_THRESHOLD_M)
                try:
                    candidates = tree.query(buf)
                    # Avoid truthiness on numpy arrays; normalize to a list
                    if candidates is None:
                        candidates = []
                    elif not isinstance(candidates, list):
                        try:
                            candidates = list(candidates)
                        except Exception:
                            candidates = []
                except Exception as q_err:
                    print(f"   ⚠️  STRtree query error for one light: {q_err}")
                    continue
                for candidate in candidates:
                    geom = candidate
                    if not hasattr(geom, 'geom_type'):
                        try:
                            geom = edge_geoms[int(candidate)]
                        except Exception:
                            continue
                    try:
                        if light_pt.distance(geom) <= LIGHT_PROXIMITY_THRESHOLD_M:
                            key = id_to_key.get(id(geom))
                            if not key:
                                try:
                                    key = wkb_to_key.get(wkb_dumps(geom))
                                except Exception:
                                    key = None
                            if key:
                                counts[key] = counts.get(key, 0) + 1
                    except Exception:
                        # Skip any bad geometry
                        continue

            for (u, v, k), cnt in counts.items():
                if G_proj.has_edge(u, v, k):
                    G_proj.edges[u, v, k]['light_count'] = cnt

            print(f"   ✓ Counted lights with STRtree proximity ({LIGHT_PROXIMITY_THRESHOLD_M}m) allowing multi-edge attribution")
            
            # Clean up spatial structures to free memory
            mem_before_cleanup = _get_mem_mb()
            del tree, edge_geoms, edge_keys, id_to_key, wkb_to_key, counts
            mem_after_cleanup = _get_mem_mb()
            print(f"   ✓ Cleaned up STRtree structures [mem: {mem_after_cleanup:.1f} MB, Δ {mem_after_cleanup - mem_before_cleanup:.1f} MB]")

            # quick stats to verify lights applied
            edge_counts = [d.get('light_count', 0) for _, _, _, d in G_proj.edges(keys=True, data=True)]
            lit_edges = sum(1 for c in edge_counts if c > 0)
            max_lights = max(edge_counts) if edge_counts else 0
            print(f"   ▶ Lit edges: {lit_edges}/{len(edge_counts)} (max lights on an edge: {max_lights})")

        except Exception as e:
            print(f"   ⚠️  Proximity check failed: {e} — setting all light counts to 0")
            for u, v, k, data in G_proj.edges(keys=True, data=True):
                data['light_count'] = 0

    # Add basic travel metrics to projected graph
    print("   Adding speeds/travel times to projected graph...")
    G_proj = add_edge_speeds(G_proj)
    G_proj = add_edge_travel_times(G_proj)
    mem_after_speeds = _get_mem_mb()
    print(f"   ✓ Speeds/times added [mem: {mem_after_speeds:.1f} MB]")

    # Fetch NLCD raster once for bbox
    print("   Fetching NLCD land cover raster for bbox once...")
    nlcd_raster, nlcd_bounds = fetch_nlcd_raster(bbox)
    mem_after_nlcd = _get_mem_mb()
    if nlcd_raster is None or nlcd_bounds is None:
        print("   ⚠️ NLCD raster unavailable; using default land risk")
    else:
        raster_size_mb = nlcd_raster.nbytes / 1024 / 1024 if nlcd_raster is not None else 0
        print(f"   ✓ NLCD raster loaded: shape={nlcd_raster.shape}, {raster_size_mb:.1f} MB raw [mem: {mem_after_nlcd:.1f} MB, Δ +{mem_after_nlcd - mem_after_speeds:.1f} MB]")

    # Prepare transformer for midpoint sampling
    target_crs = G_proj.graph.get('crs') if isinstance(G_proj.graph, dict) else None
    transformer_to_latlon = None
    if target_crs:
        try:
            from pyproj import Transformer
            transformer_to_latlon = Transformer.from_crs(target_crs, 'EPSG:4326', always_xy=True)
        except Exception:
            transformer_to_latlon = None

    # Fetch sidewalk coverage for the bbox
    print("   Fetching sidewalk coverage data...")
    sidewalk_data = fetch_sidewalk_coverage(bbox)
    print(f"   ✓ Sidewalk data fetched for {len(sidewalk_data)} ways")
    
    # Fetch open businesses for the bbox
    print("   Fetching nearby open businesses...")
    businesses = fetch_open_businesses(bbox)
    print(f"   ✓ Found {len(businesses)} open businesses")
    
    # Build a spatial index of businesses for proximity scoring (simple approach)
    business_locations = set()
    if businesses:
        for lat, lon, name, btype in businesses:
            # Grid-based bucketing: convert to grid cells for faster proximity checks
            cell_lat = round(lat * 1000)  # ~111m precision
            cell_lon = round(lon * 1000)
            business_locations.add((cell_lat, cell_lon))

    # Scoring: safety = w_darkness*darkness_score + w_sidewalk*sidewalk_score + w_business*business_score + w_land*land_risk
    print("   Scoring edges for walking safety...")
    land_samples = 0
    land_unknown = 0
    land_codes = []
    for u, v, k, data in G_proj.edges(keys=True, data=True):
        # Darkness score from lights per meter (higher when darker)
        length_m = data.get('length', 0.0)
        if not length_m or length_m <= 0:
            # fall back to geometry length if available
            geom = data.get('geometry')
            try:
                if geom is not None and hasattr(geom, 'length'):
                    length_m = float(geom.length)
            except Exception:
                length_m = 0.0
        light_count = float(data.get('light_count', 0))
        lights_per_meter = (light_count / length_m) if length_m and length_m > 0 else 0.0
        darkness_score = 1.0 / (1.0 + (lights_per_meter * DENSITY_SCALE))

        # Sidewalk score: higher when sidewalk is available (safer for walking)
        sidewalk_score = 0.5  # Default neutral score
        edge_key = f"{u}_{v}"
        if edge_key in sidewalk_data:
            sw_info = sidewalk_data[edge_key]
            if sw_info.get('has_sidewalk', False):
                sidewalk_score = 1.0  # Safe: has dedicated sidewalk
            elif sw_info.get('sidewalk_left', False) or sw_info.get('sidewalk_right', False):
                sidewalk_score = 0.8  # Good: has sidewalk on at least one side
            else:
                sidewalk_score = 0.3  # Poor: no sidewalk
        
        # Business proximity score: higher when near open businesses (feels safer)
        business_score = 0.5  # Default neutral
        try:
            if len(data.get('geometry', [])) > 0 or True:  # Check if we can get midpoint
                geom = data.get('geometry')
                if geom is not None and hasattr(geom, 'interpolate'):
                    mid_pt = geom.interpolate(0.5, normalized=True)
                    mid_lat, mid_lon = transformer_to_latlon.transform(mid_pt.x, mid_pt.y) if transformer_to_latlon else (0, 0)
                else:
                    lon1, lat1 = G_proj.nodes[u]['x'], G_proj.nodes[u]['y']
                    lon2, lat2 = G_proj.nodes[v]['x'], G_proj.nodes[v]['y']
                    mid_lon, mid_lat = (lon1 + lon2) / 2.0, (lat1 + lat2) / 2.0
                
                # Check business proximity (within ~500m / ~5 grid cells)
                cell_lat = round(mid_lat * 1000)
                cell_lon = round(mid_lon * 1000)
                nearby_businesses = False
                for dlat in range(-5, 6):
                    for dlon in range(-5, 6):
                        if (cell_lat + dlat, cell_lon + dlon) in business_locations:
                            nearby_businesses = True
                            break
                    if nearby_businesses:
                        break
                
                if nearby_businesses:
                    business_score = 0.9  # Good: near businesses
                else:
                    business_score = 0.4  # Poor: isolated area
        except Exception:
            pass

        # Land cover risk from NLCD raster at midpoint
        land_risk = 0.6
        land_label = "Unknown"
        if transformer_to_latlon is not None and nlcd_raster is not None and nlcd_bounds is not None:
            try:
                geom = data.get('geometry')
                if geom is not None and hasattr(geom, 'interpolate'):
                    mid_pt = geom.interpolate(0.5, normalized=True)
                    lon, lat = transformer_to_latlon.transform(mid_pt.x, mid_pt.y)
                else:
                    lon1, lat1 = G_proj.nodes[u]['x'], G_proj.nodes[u]['y']
                    lon2, lat2 = G_proj.nodes[v]['x'], G_proj.nodes[v]['y']
                    midx, midy = (lon1 + lon2) / 2.0, (lat1 + lat2) / 2.0
                    lon, lat = transformer_to_latlon.transform(midx, midy)

                code = sample_nlcd_code(lon, lat, nlcd_raster, nlcd_bounds)
                lr, lbl = land_risk_from_nlcd(code)
                land_risk = lr
                land_label = lbl
                land_samples += 1
                if code is None:
                    land_unknown += 1
                else:
                    land_codes.append(code)
            except Exception:
                pass

        # Calculate walking safety score (higher = safer)
        # Invert components so higher values mean safer
        safety = (W_DARKNESS * darkness_score) + (W_SIDEWALK * sidewalk_score) + (W_BUSINESS * business_score) + (W_LAND * (1.0 - land_risk))
        data['darkness_score'] = darkness_score
        data['sidewalk_score'] = sidewalk_score
        data['business_score'] = business_score
        data['land_risk'] = land_risk
        data['land_label'] = land_label
        data['safety_score'] = float(safety)

    # Debug summary for land cover sampling
    mem_after_scoring = _get_mem_mb()
    if land_samples == 0:
        print("   ⚠️ No NLCD samples were taken (raster or transform missing)")
    else:
        uniq = {c: land_codes.count(c) for c in set(land_codes)} if land_codes else {}
        print(f"   ▶ NLCD samples: {land_samples} (unknown: {land_unknown}) codes_seen: {uniq}")
    print(f"   ✓ Edge scoring complete [mem: {mem_after_scoring:.1f} MB]")
    
    # Release NLCD raster from memory after scoring
    mem_before_nlcd_del = _get_mem_mb()
    del nlcd_raster
    nlcd_raster = None
    mem_after_nlcd_del = _get_mem_mb()
    print(f"   ✓ NLCD raster released [mem: {mem_after_nlcd_del:.1f} MB, Δ {mem_after_nlcd_del - mem_before_nlcd_del:.1f} MB]")

    # Create an optimized routing weight (travel_time scaled by safety)
    for u, v, k, data in G_proj.edges(keys=True, data=True):
        time_sec = data.get('travel_time', 1)
        safety_factor = 1.0 + (data.get('safety_score', 100.0) / 100.0)
        data['optimized_weight'] = time_sec * safety_factor

    # Return graph in lat/lon for plotting and routing convenience
    mem_before_reproject = _get_mem_mb()
    G_latlon = project_graph(G_proj, to_crs='EPSG:4326')
    mem_after_reproject = _get_mem_mb()
    print(f"   ✓ Graph re-projected to lat/lon [mem: {mem_after_reproject:.1f} MB, Δ +{mem_after_reproject - mem_before_reproject:.1f} MB]")
    
    # Clean up intermediate copies to free memory
    mem_before_graph_del = _get_mem_mb()
    del G_proj
    del G
    mem_after_graph_del = _get_mem_mb()
    print(f"   ✓ Intermediate graphs released [mem: {mem_after_graph_del:.1f} MB, Δ {mem_after_graph_del - mem_before_graph_del:.1f} MB]")
    
    mem_final = _get_mem_mb()
    print(f"   ✓ Build complete [final mem: {mem_final:.1f} MB, total Δ +{mem_final - mem_start:.1f} MB]")
    
    return G_latlon, lights_latlon
