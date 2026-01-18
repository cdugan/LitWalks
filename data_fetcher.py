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
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
BUSINESSES_CACHE_FILE = "businesses_cache.json"
SIDEWALKS_CACHE_FILE = "sidewalks_cache.json"

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

# --- CACHE HELPERS ---
def load_cache():
    # kept for backward compatibility; returns mapillary-style cache if present
    if os.path.exists(DUKE_CACHE_FILE):
        try:
            with open(DUKE_CACHE_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}


def save_cache(cache_data):
    with open(DUKE_CACHE_FILE, 'w') as f:
        json.dump(cache_data, f)


# --- BUSINESS DATA FETCHING (via Overpass API) ---
def fetch_open_businesses(bbox, current_time=None):
    """Fetch currently open businesses near a bbox using Overpass API.
    
    bbox: (north, south, east, west)
    current_time: datetime object or None (uses current time if None)
    
    Returns list of (lat, lon, name, type) tuples for open businesses.
    """
    if current_time is None:
        import datetime
        current_time = datetime.datetime.now()
    
    businesses_cache = _load_json_cache(BUSINESSES_CACHE_FILE)
    bbox_key = f"{bbox[0]:.4f}_{bbox[1]:.4f}_{bbox[2]:.4f}_{bbox[3]:.4f}"
    
    # Check cache (valid for 1 hour since business hours change)
    if bbox_key in businesses_cache:
        cached_time = businesses_cache[bbox_key].get('timestamp', 0)
        if time.time() - cached_time < 3600:
            return businesses_cache[bbox_key].get('businesses', [])
    
    north, south, east, west = bbox
    
    # Overpass QL query for amenities/shops that typically have business hours
    query = f"""
    [bbox:{south},{west},{north},{east}];
    (
      node["amenity"~"cafe|restaurant|bar|pub|shop|bank|library|gym|pharmacy"]["opening_hours"];
      way["amenity"~"cafe|restaurant|bar|pub|shop|bank|library|gym|pharmacy"]["opening_hours"];
      node["shop"];
      way["shop"];
    );
    out body;
    """
    
    try:
        response = requests.post(OVERPASS_URL, data=query, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"   ⚠️ Overpass API error for businesses: {e}")
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
    
    print(f"   Fetched {len(businesses)} open businesses for bbox {bbox_key}")
    return businesses


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
    query = f"""
    [bbox:{south},{west},{north},{east}];
    (
      way["highway"]["sidewalk"];
      way["footway"];
      way["path"]["foot"="yes"];
    );
    out body geom;
    """
    
    try:
        response = requests.post(OVERPASS_URL, data=query, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"   ⚠️ Overpass API error for sidewalks: {e}")
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
