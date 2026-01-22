import requests
import time
import json
import os
import math
import io
from functools import lru_cache

from PIL import Image # Pip install Pillow if needed
import numpy as np

# Duke streetlights API
DUKE_URL = "https://salor-api.duke-energy.app/streetlights"
DUKE_CACHE_FILE = "duke_cache.json"

# MRLC / NLCD WMS
NLCD_WMS_URL = "https://www.mrlc.gov/geoserver/mrlc_display/wms"
NLCD_LAYER = "NLCD_2021_Land_Cover_L48"
NLCD_CACHE_FILE = "nlcd_cache.png"

# OpenStreetMap (OSM) Overpass API for sidewalks and businesses
# List of Overpass mirrors to try in order (primary may be overloaded)
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
]
BUSINESSES_CACHE_FILE = "businesses_cache.json"
SIDEWALKS_CACHE_FILE = "sidewalks_cache.json"

# Google Places API
GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
BUSINESSES_PROVIDER = os.environ.get("BUSINESSES_PROVIDER", "").strip().lower()  # 'google' | 'osm' | ''
SKIP_PLACES_CACHE = os.environ.get("SKIP_PLACES_CACHE", "").lower() in ("1", "true", "yes")

def fetch_duke_lights(bbox):
    """
    Fetch Duke streetlights within bbox and return list of (lat, lon) tuples.
    bbox expected as (north, south, east, west)
    Uses local JSON cache in `DUKE_CACHE_FILE` keyed by rounded bbox.
    """
    north, south, east, west = bbox

    bbox_key = f"{round(north,5)},{round(south,5)},{round(east,5)},{round(west,5)}"
    duke_cache = _load_json_cache(DUKE_CACHE_FILE)
    if bbox_key in duke_cache:
        try:
            items = duke_cache[bbox_key]
            return _parse_duke_items_to_latlon(items)
        except Exception:
            return []

    params = {
        'swLat': south,
        'swLong': west,
        'neLat': north,
        'neLong': east
    }

    try:
        resp = requests.get(DUKE_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"   ⚠️ Duke API error: {e}")
        return []

    duke_cache[bbox_key] = data
    _save_json_cache(DUKE_CACHE_FILE, duke_cache)

    return _parse_duke_items_to_latlon(data)

def frange(start, stop, step):
    x = start
    while x < stop:
        yield x
        x += step


def get_satellite_brightness(lat, lon, bbox, img):
    """
    (Legacy stub retained for compatibility; returns 0.)
    """
    return 0


def fetch_nlcd_raster(bbox, width=1024):
    """Fetch NLCD raster for bbox via WMS GetMap; returns (np.ndarray, (minx,miny,maxx,maxy)).

    Tries to retrieve a raw GeoTIFF first to preserve class codes; falls back to PNG if needed.
    Uses EPSG:4326, WMS 1.1.1. Attempts to cache to disk (NLCD_CACHE_FILE).
    """
    north, south, east, west = bbox
    minx, miny, maxx, maxy = west, south, east, north
    x_span = maxx - minx
    y_span = maxy - miny
    if x_span <= 0 or y_span <= 0:
        raise ValueError("Invalid bbox for NLCD fetch")
    height = max(1, int(width * (y_span / x_span)))

    base_params = {
        "service": "WMS",
        "version": "1.1.1",
        "request": "GetMap",
        "layers": NLCD_LAYER,
        "srs": "EPSG:4326",
        "bbox": f"{minx},{miny},{maxx},{maxy}",
        "width": width,
        "height": height,
        "styles": "",
        "transparent": "false",
    }

    content = None
    used_format = None
    last_err = None
    for fmt in ["image/tiff", "image/geotiff", "image/png"]:
        params = {**base_params, "format": fmt}
        try:
            resp = requests.get(NLCD_WMS_URL, params=params, timeout=30)
            resp.raise_for_status()
            if resp.content:
                content = resp.content
                used_format = fmt
                break
            last_err = RuntimeError("Empty NLCD response")
        except Exception as e:
            last_err = e
            continue

    if content is None:
        print(f"   ⚠️ NLCD GetMap failed: {last_err}")
        # fallback to cache if exists
        if os.path.exists(NLCD_CACHE_FILE):
            try:
                with open(NLCD_CACHE_FILE, "rb") as f:
                    content = f.read()
                used_format = "cache"
                print("   Using cached NLCD raster")
            except Exception:
                return None, None
        else:
            return None, None

    try:
        img = Image.open(io.BytesIO(content))
        arr = np.array(img)
        if arr.ndim == 3 and arr.shape[2] >= 1:
            arr = arr[:, :, 0]
        # cache what we decoded
        try:
            with open(NLCD_CACHE_FILE, "wb") as f:
                f.write(content)
        except Exception:
            pass
        try:
            vals, counts = np.unique(arr, return_counts=True)
            order = np.argsort(counts)[::-1]
            preview = {int(vals[i]): int(counts[i]) for i in order[:10]}
            print(f"   NLCD raster loaded ({used_format}): shape {arr.shape} dtype {arr.dtype} top_vals {preview}")
        except Exception:
            print(f"   NLCD raster loaded ({used_format}): shape {arr.shape} dtype {arr.dtype}")
        return arr, (minx, miny, maxx, maxy)
    except Exception as e:
        print(f"   ⚠️ Failed to decode NLCD image ({used_format}): {e}")
        return None, None


# --- NLCD LAND COVER VIA WMS ---
@lru_cache(maxsize=2048)
def fetch_nlcd_class(lat: float, lon: float):
    """Fetch NLCD land cover class code and label for a single point.

    Uses WMS 1.1.1 GetFeatureInfo on the MRLC NLCD layer. Returns (code, label).
    Caches responses per lat/lon to avoid repeated calls.
    """
    # Build a tiny bbox around the point to query the pixel
    delta = 0.0005  # ~50m at these latitudes
    minx = lon - delta
    maxx = lon + delta
    miny = lat - delta
    maxy = lat + delta

    params = {
        "service": "WMS",
        "version": "1.1.1",
        "request": "GetFeatureInfo",
        "layers": NLCD_LAYER,
        "query_layers": NLCD_LAYER,
        "srs": "EPSG:4326",
        "bbox": f"{minx},{miny},{maxx},{maxy}",
        "width": 101,
        "height": 101,
        "x": 50,
        "y": 50,
        "info_format": "application/json",
    }

    try:
        resp = requests.get(NLCD_WMS_URL, params=params, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"   ⚠️ NLCD WMS request failed: {e}")
        return None, None

    ctype = resp.headers.get("Content-Type", "").lower()
    if "json" in ctype:
        try:
            data = resp.json()
            # Many WMS servers return a "features" array with properties incl. 'GRAY_INDEX'
            if isinstance(data, dict):
                if "features" in data and data["features"]:
                    props = data["features"][0].get("properties", {})
                    code = props.get("GRAY_INDEX") or props.get("value")
                    return _nlcd_code_to_int(code), _nlcd_label(code)
                # Sometimes value sits at top level
                if "value" in data:
                    code = data.get("value")
                    return _nlcd_code_to_int(code), _nlcd_label(code)
        except Exception:
            pass

    # Fallback: try text and parse first int we see
    text = resp.text
    code = _extract_first_int(text)
    return _nlcd_code_to_int(code), _nlcd_label(code)


def _extract_first_int(text):
    try:
        import re
        m = re.search(r"(-?\d+)", text)
        if m:
            return int(m.group(1))
    except Exception:
        return None
    return None


def _nlcd_code_to_int(code):
    try:
        return int(code)
    except Exception:
        return None


def _nlcd_label(code):
    lookup = {
        11: "Open Water",
        12: "Perennial Ice/Snow",
        21: "Developed, Open Space",
        22: "Developed, Low Intensity",
        23: "Developed, Medium Intensity",
        24: "Developed, High Intensity",
        31: "Barren Land",
        41: "Deciduous Forest",
        42: "Evergreen Forest",
        43: "Mixed Forest",
        52: "Shrub/Scrub",
        71: "Grassland/Herbaceous",
        81: "Pasture/Hay",
        82: "Cultivated Crops",
        90: "Woody Wetlands",
        95: "Emergent Herbaceous Wetlands",
    }
    try:
        return lookup.get(int(code), "Unknown")
    except Exception:
        return "Unknown"


# --- DUKE CACHE HELPERS & PARSING ---
def _load_json_cache(path):
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_json_cache(path, data):
    try:
        with open(path, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass


def _parse_duke_items_to_latlon(data):
    """Accepts raw API response (likely a list of dicts) and returns list of (lat, lon) tuples."""
    items = []
    if isinstance(data, dict):
        candidates = data.get('data') or data.get('results') or []
        if isinstance(candidates, list):
            data = candidates

    if not isinstance(data, list):
        return []

    for it in data:
        try:
            if isinstance(it, dict):
                keys = {k.lower(): k for k in it.keys()}
                if 'latitude' in keys and 'longitude' in keys:
                    lat = float(it[keys['latitude']])
                    lon = float(it[keys['longitude']])
                    items.append((lat, lon))
                    continue
                if 'lat' in keys and ('lng' in keys or 'lon' in keys):
                    lat = float(it[keys['lat']])
                    lon = float(it[keys.get('lng', keys.get('lon'))])
                    items.append((lat, lon))
                    continue
            if isinstance(it, (list, tuple)) and len(it) >= 2:
                a = float(it[0]); b = float(it[1])
                if -90 <= a <= 90 and -180 <= b <= 180:
                    items.append((a, b))
                elif -90 <= b <= 90 and -180 <= a <= 180:
                    items.append((b, a))
        except Exception:
            continue

    return items


# --- BUSINESS DATA FETCHING (Google Places or Overpass) ---
def fetch_businesses(bbox):
    """Fetch businesses using Google Places if configured, else Overpass.

    Returns list of (lat, lon, name, type) tuples.
    """
    preferred = BUSINESSES_PROVIDER
    if preferred == "google" or GOOGLE_PLACES_API_KEY:
        items = fetch_google_places_businesses(bbox, GOOGLE_PLACES_API_KEY)
        if items:
            return items
        # Fallback to OSM if Google fails
        print("   ⚠️ Google Places returned no results or failed; falling back to Overpass")
    return fetch_open_businesses(bbox)


def _bbox_centroid(bbox):
    n, s, e, w = bbox
    return ( (n + s) / 2.0, (e + w) / 2.0 )


def fetch_google_places_businesses(bbox, api_key, radius_m=400, min_reviews=1, max_reviews=999999):
    """Fetch businesses in bbox via Google Places API (New).

    Uses the new Places API v1 endpoint with searchNearby method.
    Strategy: sample a grid of centers over bbox and call searchNearby.
    Deduplicate by place_id. Returns list of (lat, lon, name, type, hours, review_count, is_open).
    
    Args:
        min_reviews: Filter for businesses with at least this many reviews (less crowded)
        max_reviews: Filter for businesses with at most this many reviews (avoid very popular)
    """
    if not api_key:
        print("   DEBUG: No Google Places API key provided")
        return []

    # Cache key distinguishes provider and parameters
    # Using aggressive caching (24 hours) to minimize expensive Places API calls
    cache = _load_json_cache(BUSINESSES_CACHE_FILE)
    bbox_key = f"google_{bbox[0]:.4f}_{bbox[1]:.4f}_{bbox[2]:.4f}_{bbox[3]:.4f}_{radius_m}_{min_reviews}_{max_reviews}"
    if not SKIP_PLACES_CACHE and bbox_key in cache:
        cached_time = cache[bbox_key].get('timestamp', 0)
        cached_businesses = cache[bbox_key].get('businesses', [])
        # Cache for 24 hours (only query Places API once per day, minimizes quota usage)
        # But skip cache if it has 0 businesses (likely a previous API error)
        if time.time() - cached_time < 86400 and len(cached_businesses) > 0:
            print(f"   ✓ Using cached Google Places data ({len(cached_businesses)} businesses, {int((time.time() - cached_time)/3600)}h old)")
            return cached_businesses
        elif len(cached_businesses) == 0:
            print(f"   ⚠️ Cached Google Places data has 0 businesses, re-fetching...")
    elif SKIP_PLACES_CACHE:
        print(f"   DEBUG: SKIP_PLACES_CACHE=1, bypassing cache")

    north, south, east, west = bbox
    
    base_url = "https://places.googleapis.com/v1/places:searchNearby"
    all_results = {}
    
    # Debugging counters
    total_raw_results = 0
    filtered_by_review_count = 0
    filtered_by_bbox = 0
    
    headers = {
        "X-Goog-Api-Key": api_key,
        "Content-Type": "application/json",
        "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.types,places.userRatingCount"
    }

    def _do_request(center_lat, center_lon, radius):
        try:
            payload = {
                "locationRestriction": {
                    "circle": {
                        "center": {
                            "latitude": center_lat,
                            "longitude": center_lon
                        },
                        "radius": radius
                    }
                },
                "includedTypes": [
                    "restaurant",
                    "cafe",
                    "bar",
                    "bakery",
                    "meal_takeaway",
                    "meal_delivery"
                ],
                "maxResultCount": 20
            }
            
            resp = requests.post(base_url, json=payload, headers=headers, timeout=30)
            data = resp.json()
            
            # Log API response details for debugging
            if resp.status_code != 200:
                print(f"   DEBUG: Google Places API response - HTTP {resp.status_code}")
                if 'error' in data:
                    error_msg = data['error'].get('message', 'No error message provided')
                    print(f"   ⚠️ Google Places error: {error_msg}")
                return None
            
            result_count = len(data.get('places', []))
            
            return data
        except Exception as e:
            print(f"   ⚠️ Google Places error: {e}")
            return None

    # Use a fine grid of circles to ensure comprehensive coverage
    # For a ~1 mile square area, use 3x3 grid with 300m radius (overlapping circles)
    lat_steps = 3
    lon_steps = 3
    lat_min, lat_max = south, north
    lon_min, lon_max = west, east

    def linspace(a, b, n):
        if n == 1:
            return [(a + b) / 2.0]
        step = (b - a) / (n - 1)
        return [a + i * step for i in range(n)]

    centers = [(lat, lon) for lat in linspace(lat_min, lat_max, lat_steps)
                           for lon in linspace(lon_min, lon_max, lon_steps)]

    print(f"   DEBUG: Using searchNearby with {len(centers)} grid points (radius={radius_m}m)")
    
    for idx, (center_lat, center_lon) in enumerate(centers):
        print(f"   DEBUG: Grid point {idx+1}/{len(centers)}: ({center_lat:.5f}, {center_lon:.5f})")
        data = _do_request(center_lat, center_lon, radius_m)
        if not data:
            continue
            
        places = data.get("places", [])
        total_raw_results += len(places)
        
        for place in places:
            place_id = place.get("id")
            if not place_id:
                continue
                
            name = place.get("displayName", {}).get("text", "N/A")
            loc_data = place.get("location", {})
            lat = loc_data.get("latitude")
            lon = loc_data.get("longitude")
            
            if lat is None or lon is None:
                continue
            
            # Filter by bbox - ensure we only include businesses strictly within the area
            if not (south <= lat <= north and west <= lon <= east):
                filtered_by_bbox += 1
                continue
                
            types = place.get("types", [])
            primary_type = types[0] if types else "unknown"
            
            # Get review count
            review_count = place.get("userRatingCount", 0)
            
            # Filter by minimum review count only
            if review_count < min_reviews:
                filtered_by_review_count += 1
                continue
            
            # Check if already seen (deduplication across grid searches)
            if place_id in all_results:
                continue
            
            all_results[place_id] = (lat, lon, name, primary_type, [], review_count, None)

    businesses = list(all_results.values())
    
    # Log final results
    print(f"   DEBUG: Total raw results from API: {total_raw_results}")
    print(f"   DEBUG: Filtered by bbox: {filtered_by_bbox}")
    print(f"   DEBUG: Filtered by review count: {filtered_by_review_count}")
    print(f"   DEBUG: Final unique businesses: {len(businesses)}")
    
    if len(businesses) == 0:
        print(f"   ⚠️ No businesses found matching criteria (min_reviews={min_reviews})")
        print(f"   DEBUG: Try adjusting review filters or check if businesses exist in the area")
    
    cache[bbox_key] = {
        'timestamp': time.time(),
        'businesses': businesses,
        'provider': 'google',
        'count': len(businesses),
        'bbox': bbox,
        'radius_m': radius_m,
        'min_reviews': min_reviews,
        'max_reviews': max_reviews,
        'note': 'Cached with full hours/reviews for time-based filtering during routing'
    }
    _save_json_cache(BUSINESSES_CACHE_FILE, cache)
    print(f"   ✓ Fetched {len(businesses)} businesses from Google Places API (cached for 24h)")
    return businesses
def fetch_open_businesses(bbox, current_time=None):
    """Fetch all businesses near a bbox using Overpass API (ignores opening hours).
    
    bbox: (north, south, east, west)
    current_time: ignored (kept for backwards compatibility)
    
    Returns list of (lat, lon, name, type) tuples for all businesses.
    """
    # Ignore timing - just fetch all businesses
    
    businesses_cache = _load_json_cache(BUSINESSES_CACHE_FILE)
    bbox_key = f"{bbox[0]:.4f}_{bbox[1]:.4f}_{bbox[2]:.4f}_{bbox[3]:.4f}"
    
    # Check cache (extended to 24 hours to minimize Overpass API calls)\n    if bbox_key in businesses_cache:\n        cached_time = businesses_cache[bbox_key].get('timestamp', 0)\n        if time.time() - cached_time < 86400:\n            cached_businesses = businesses_cache[bbox_key].get('businesses', [])\n            print(f\"   ✓ Using cached Overpass data ({len(cached_businesses)} businesses, {int((time.time() - cached_time)/3600)}h old)\")\n            return cached_businesses
    
    north, south, east, west = bbox
    
    # Overpass QL query for amenities/shops - fetch all business types
    # Include [timeout:60][out:json] directives in proper Overpass QL format
    query = f"""[bbox:{south},{west},{north},{east}][timeout:60][out:json];
(
  node["shop"];
  node["amenity"~"cafe|restaurant|bar|pub|fast_food|food_court|bank|pharmacy|cinema|theatre|library|post_office"];
);
out center;
    """
    
    # Query Overpass with failover to mirrors and retry logic
    data, success = _query_overpass_with_failover(query, max_retries=5)
    if not success:
        print(f"   ⚠️ Overpass business query failed, skipping businesses")
        return []
    
    businesses = []
    if 'elements' in data:
        for elem in data['elements']:
            try:
                lat = elem.get('lat')
                lon = elem.get('lon')
                tags = elem.get('tags', {})
                name = tags.get('name', 'Unknown Business')
                amenity = tags.get('amenity', '')
                shop = tags.get('shop', '')
                business_type = amenity if amenity else shop
                
                if lat is not None and lon is not None:
                    businesses.append((lat, lon, name, business_type))
            except Exception:
                continue
    
    # Cache the results
    if businesses_cache.get(bbox_key) is None:
        businesses_cache[bbox_key] = {}
    businesses_cache[bbox_key]['businesses'] = businesses
    businesses_cache[bbox_key]['timestamp'] = time.time()
    _save_json_cache(BUSINESSES_CACHE_FILE, businesses_cache)
    
    print(f"   ✓ Fetched {len(businesses)} businesses from Overpass API")
    return businesses


# --- OVERPASS API HELPER ---
def _query_overpass_with_failover(query: str, max_retries: int = 5):
    """Query Overpass API with mirror failover and retry logic.
    
    Returns (data_dict, success_bool). On failure, returns ({}, False).
    """
    retry_delay = 3
    for attempt in range(max_retries):
        # Try each mirror in order
        for mirror_idx, overpass_url in enumerate(OVERPASS_URLS):
            try:
                if attempt == 0 and mirror_idx == 0:
                    print(f"   DEBUG: Query format:\n{query[:100]}...")
                
                url_label = f"Mirror {mirror_idx+1}/{len(OVERPASS_URLS)}"
                print(f"   Querying Overpass {url_label} (attempt {attempt + 1}/{max_retries})...")
                
                response = requests.post(overpass_url, data=query, timeout=120)
                
                # Check for rate limit or server errors
                if response.status_code == 429:
                    print(f"     Rate limited by {url_label}, trying next mirror...")
                    continue
                elif response.status_code == 504:
                    print(f"     Gateway timeout from {url_label}, trying next mirror...")
                    continue
                elif response.status_code >= 500:
                    print(f"     Server error ({response.status_code}) from {url_label}, trying next mirror...")
                    continue
                elif response.status_code >= 400:
                    raise Exception(f"Client error ({response.status_code}): {response.text[:100]}")
                
                response.raise_for_status()
                
                # Check if response has content
                if not response.text or not response.text.strip():
                    print(f"     Empty response from {url_label}, trying next mirror...")
                    continue
                
                data = response.json()
                print(f"   ✓ Success from {url_label}")
                return (data, True)
                
            except requests.exceptions.Timeout:
                print(f"     Timeout from {url_label}, trying next mirror...")
                continue
            except Exception as e:
                print(f"     Error from {url_label}: {e}")
                continue
        
        # All mirrors failed for this attempt, wait and retry
        if attempt < max_retries - 1:
            print(f"   All mirrors failed, retrying in {retry_delay}s...")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
    
    print(f"   ⚠️ Overpass API failed after {max_retries} attempts on all mirrors")
    return ({}, False)


# --- SIDEWALK DATA FETCHING (via Overpass API) ---
def fetch_sidewalk_coverage(bbox):
    """Fetch sidewalk information for streets in a bbox using Overpass API.
    
    bbox: (north, south, east, west)
    
    Returns dict mapping edge endpoints to sidewalk info: 
    {'has_sidewalk': bool, 'sidewalk_left': bool, 'sidewalk_right': bool}
    """
    sidewalks_cache = _load_json_cache(SIDEWALKS_CACHE_FILE)
    bbox_key = f"{bbox[0]:.4f}_{bbox[1]:.4f}_{bbox[2]:.4f}_{bbox[3]:.4f}"
    
    # Check cache (valid for 24 hours since sidewalks rarely change)
    if bbox_key in sidewalks_cache:
        cached_time = sidewalks_cache[bbox_key].get('timestamp', 0)
        if time.time() - cached_time < 86400:
            return sidewalks_cache[bbox_key].get('sidewalks', {})
    
    north, south, east, west = bbox
    
    # Overpass QL query for ways with sidewalk information
    # Include [timeout:60][out:json] directives in proper Overpass QL format
    query = f"""[bbox:{south},{west},{north},{east}][timeout:60][out:json];
way["highway"]["sidewalk"];
out body;
    """
    
    # Query Overpass with failover to mirrors and retry logic
    data, success = _query_overpass_with_failover(query, max_retries=5)
    if not success:
        print(f"   ⚠️ Overpass sidewalk query failed, skipping sidewalks")
        return {}
    
    sidewalk_info = {}
    if 'elements' in data:
        for way in data['elements']:
            try:
                if way.get('type') != 'way':
                    continue
                    
                tags = way.get('tags', {})
                nodes = way.get('nodes', [])
                
                if len(nodes) < 2:
                    continue
                
                sidewalk = tags.get('sidewalk', 'no')
                sidewalk_left = tags.get('sidewalk:left', sidewalk) in ['yes', 'left']
                sidewalk_right = tags.get('sidewalk:right', sidewalk) in ['yes', 'right']
                
                # Also detect dedicated paths
                has_sidewalk = (
                    sidewalk == 'yes' or 
                    sidewalk_left or sidewalk_right or
                    tags.get('footway') in ['sidewalk', 'yes'] or
                    tags.get('path') == 'yes'
                )
                
                # Create edge key from node ids
                edge_key = f"{nodes[0]}_{nodes[-1]}"
                sidewalk_info[edge_key] = {
                    'has_sidewalk': has_sidewalk,
                    'sidewalk_left': sidewalk_left,
                    'sidewalk_right': sidewalk_right
                }
            except Exception:
                continue
    
    # Cache the results
    if sidewalks_cache.get(bbox_key) is None:
        sidewalks_cache[bbox_key] = {}
    sidewalks_cache[bbox_key]['sidewalks'] = sidewalk_info
    sidewalks_cache[bbox_key]['timestamp'] = time.time()
    _save_json_cache(SIDEWALKS_CACHE_FILE, sidewalks_cache)
    
    print(f"   Fetched sidewalk data for {len(sidewalk_info)} ways in bbox {bbox_key}")
    return sidewalk_info
