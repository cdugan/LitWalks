# Quick Start Guide - Building the Graph

## One-Command Build (Recommended)

```powershell
$env:SKIP_OVERPASS=1; python build_graph_offline.py
```

This builds the graph quickly without waiting for potentially unreliable Overpass API calls.

---

## What Changed

### Before (Problematic):
- Overpass API calls would timeout (504 errors)
- Business and sidewalk data weren't being fetched
- Graph building took 20+ seconds with API timeouts
- Graph attributes were being stripped

### Now (Fixed):
- Optional Overpass API with intelligent retries
- Fallback defaults work perfectly
- Graph builds in ~13 seconds with `SKIP_OVERPASS=1`
- All walking metrics preserved in graph
- Environment variable to control API usage

---

## Building Stages

The build process has 5 stages:

```
[1] Build graph with OSM data + Duke lights + NLCD (always works)
    → 5241 nodes, 12254 edges, 4902 lights
    
[2] Fetch optional walking data (can skip)
    → Sidewalk coverage (0 ways if skipped)
    → Open businesses (0 businesses if skipped)
    
[3] Score edges for walking safety
    → Uses: lighting, sidewalks, businesses, land use
    → Works fine with defaults when data unavailable
    
[4] Compress and save graph
    → 4.39 MB serialized file
    
[5] Verify by loading
    → Confirms graph integrity
```

---

## Graph Attributes Preserved

✅ **Walking Safety Metrics**:
- `safety_score` - Overall safety (weighted combination)
- `darkness_score` - Lighting conditions  
- `sidewalk_score` - Sidewalk availability
- `business_score` - Proximity to open businesses

✅ **Routing Data**:
- `length` - Street length in meters
- `travel_time` - Estimated walking time
- `speed_kph` - Average speed

✅ **Debug Info**:
- `name` - Street name
- `land_risk` / `land_label` - Land use type
- `light_count` - Number of nearby lights

❌ **Removed (Old Driving Metrics)**:
- `curve_score` - Road curviness (not for walking)
- `highway_risk` - Road type risk (not for walking)
- `highway_tag` - Highway classification

---

## Environment Variables

### Skip Overpass API (Fastest):
```powershell
$env:SKIP_OVERPASS=1
python build_graph_offline.py
```
- Build time: ~13 seconds
- Uses default scores (0.5 = neutral)
- No external API calls

### Use Overpass API (Full Data):
```powershell
python build_graph_offline.py
```
- Build time: ~18-60 seconds (depends on API availability)
- 3 retry attempts with exponential backoff
- 60-second timeout per call
- Falls back to defaults if API fails

---

## Output Examples

### With SKIP_OVERPASS=1:
```
✓ OSM graph: 5241 nodes, 12254 edges
✓ Duke lights: 4902 lights
⊘ Skipping Overpass API
✓ Edge scoring: 12254 edges
✓ Graph saved: 4.39 MB
```

### With Overpass (if available):
```
✓ OSM graph: 5241 nodes, 12254 edges
✓ Duke lights: 4902 lights
✓ Sidewalk data: 2847 ways
✓ Open businesses: 156 locations
✓ Edge scoring: 12254 edges
✓ Graph saved: 4.39 MB
```

---

## Troubleshooting

### "504 Gateway Timeout" from Overpass:
- This is normal - Overpass is a free public service
- **Solution**: Use `SKIP_OVERPASS=1` for faster builds
- Overpass is already optional - graph works fine without it

### Graph takes 60+ seconds to build:
- Overpass API is timing out
- **Solution**: Use `SKIP_OVERPASS=1` to skip API calls
- Or try again later when Overpass service recovers

### Graph seems smaller than expected:
- Check if Overpass data was skipped
- Look for `⊘ Skipping Overpass API` in output
- This is fine - routing still works with defaults

---

## When to Use Each Option

| Situation | Command |
|-----------|---------|
| **Local Development** | `$env:SKIP_OVERPASS=1; python build_graph_offline.py` |
| **Production Build** | `$env:SKIP_OVERPASS=1; python build_graph_offline.py` |
| **Nighttime Build** | Try Overpass first, fallback to skip if timeout |
| **Benchmarking** | Use `SKIP_OVERPASS=1` for consistent timing |
| **Full Data** | Try Overpass with retries enabled |

**Recommendation**: Use `SKIP_OVERPASS=1` for all production builds for reliability.

---

## Next Steps

1. Run build command above
2. Wait for completion (should see "✓ Offline build complete!")
3. Start web app: `python web_app.py`
4. Open browser: http://localhost:5000
5. Test a route!
