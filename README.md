# LitWalks - Safe Walking Route Navigator

A web application that finds the safest walking routes using pedestrian paths, streetlight data, and safety scoring.

## Features

- **Pedestrian-First Routing**: Prioritizes footpaths and dedicated pedestrian infrastructure over roads
- **Safety Scoring**: Combines streetlight coverage, land use, and business proximity
- **Dual Route Display**: Shows both the safest route (cyan) and fastest route (magenta)
- **Real-time Visualization**: Interactive Leaflet map with route overlays

## Quick Start

### Prerequisites

- Python 3.9+
- pip

### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Build the walking graph (10-20 seconds)
python build_graph_offline.py

# Start the web server
python web_app.py
```

Open http://localhost:5000 in your browser.

### Usage

1. Click two points on the map to set start and end locations
2. View both the safest route (cyan solid line) and fastest route (magenta dashed line)
3. Compare metrics: walking time, footpath percentage, lighting, safety scores
4. Click on any road segment to see detailed safety information

## How It Works

### Data Sources

- **OpenStreetMap**: Walking network (footways, paths, roads)
- **Duke Energy API**: Streetlight locations
- **NLCD (USGS)**: Land cover classification
- **Overpass API** (optional): Business locations and sidewalk tags

### Safety Scoring

Each path segment gets a safety score (0-1) based on:

- **40%** Darkness (inverse of streetlight density)
- **30%** Footpath vs Road (binary: 1.0 for footpaths, 0.0 for roads)
- **15%** Business Proximity (safer when near commercial areas)
- **15%** Land Use (developed areas safer than forests/wetlands)

### Routing Algorithm

- **Safest Route**: Minimizes `travel_time * road_penalty / safety_score`
  - Footpaths get no penalty (1x)
  - Roads get heavy penalty (10x) to strongly prefer pedestrian paths
- **Fastest Route**: Minimizes `travel_time` only

This ensures the safe route uses footpaths whenever available, only using roads when no pedestrian alternative exists.

## Configuration

Edit `config.py` to change the bounding box:

```python
BBOX = (north, south, east, west)  # Latitude/longitude coordinates
```

After changing BBOX, rebuild the graph:

```bash
python build_graph_offline.py
```

### Build Options

```bash
# Skip Overpass API (faster, but no business/sidewalk data from OSM)
set SKIP_OVERPASS=1
python build_graph_offline.py

# Use Overpass API (slower, includes OSM business data)
set SKIP_OVERPASS=0
python build_graph_offline.py
```

## File Structure

```
LitWalks/
├── web_app.py              # Flask web server
├── graph_builder.py        # Graph construction and safety scoring
├── build_graph_offline.py  # Pre-build graph for fast loading
├── data_fetcher.py         # Duke lights, NLCD, Overpass API
├── route_visualizer.py     # Route computation utilities
├── config.py               # Bounding box configuration
├── requirements.txt        # Python dependencies
├── graph_prebuilt.pkl      # Pre-built graph (generated)
├── web/
│   ├── templates/
│   │   └── index.html      # Main UI
│   └── static/
│       ├── app.js          # Map and routing logic
│       └── style.css       # Styles
└── cache/                  # Duke/Overpass API cache files
```

## API Endpoints

- `GET /` - Main web interface
- `POST /api/route` - Calculate safe/fast routes between two points
- `GET /api/graph-data` - Full graph GeoJSON for visualization
- `GET /api/graph-data-lite` - Lightweight graph (lite loading)

## Development

### Docker Deployment

```bash
docker-compose up --build
```

### Memory Usage

- Initial load: ~150 MB
- After graph load: ~160-250 MB (depends on graph size)
- Full graph serves: ~265 MB

### Performance

- Graph build time: 10-30 seconds (depending on area size and SKIP_OVERPASS)
- Route calculation: <1 second
- Map load: 2-3 seconds

## Troubleshooting

**Graph won't build:**
- Try `set SKIP_OVERPASS=1` to skip external API calls
- Check that BBOX coordinates are valid (north > south, east > west)

**Routes not showing:**
- Clear browser cache and reload
- Check console for JavaScript errors
- Verify graph_prebuilt.pkl exists

**Slow performance:**
- Reduce BBOX size in config.py
- Use SKIP_OVERPASS=1 for faster builds

## License

This project uses data from:
- OpenStreetMap (ODbL)
- Duke Energy Public API
- USGS/MRLC NLCD
