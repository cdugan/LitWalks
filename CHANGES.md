# Changes: From Safe Driving Routes to Safe Walking Routes

## Summary
This document outlines all modifications made to transition the LitRoutes application from calculating safe driving routes to safe walking routes. The changes include new data sources, updated safety scoring algorithms, and an improved user interface focused on pedestrian needs.

---

## 1. Data Source Enhancements

### New Data Fetchers (data_fetcher.py)

#### 1.1 Business Data Fetching
- **Function**: `fetch_open_businesses(bbox, current_time=None)`
- **Purpose**: Identifies currently open businesses near the route to help pedestrians feel safer in populated areas
- **Data Source**: Overpass API (OpenStreetMap)
- **Query Types**: 
  - Amenities: cafes, restaurants, bars, pubs, shops, banks, libraries, gyms, pharmacies
  - Shops: all retail businesses
- **Caching**: 1-hour cache (business hours change frequently)
- **Returns**: List of (lat, lon, name, type) tuples

#### 1.2 Sidewalk Coverage Data
- **Function**: `fetch_sidewalk_coverage(bbox)`
- **Purpose**: Identifies routes with sidewalk infrastructure, critical for safe pedestrian navigation
- **Data Source**: Overpass API (OpenStreetMap)
- **Query Types**:
  - Ways with sidewalk tags
  - Dedicated footways
  - Paths marked for pedestrian use
- **Caching**: 24-hour cache (sidewalks rarely change)
- **Returns**: Dictionary mapping edge IDs to sidewalk info (presence, left/right availability)

#### 1.3 Cache Files Added
- `businesses_cache.json`: Stores fetched business locations and open hours data
- `sidewalks_cache.json`: Stores sidewalk information for streets in cached bounding boxes

---

## 2. Safety Scoring Algorithm Changes

### Previous (Driving Routes) - graph_builder.py
```
safety_score = (W_CURVE * curve_score) + (W_DARKNESS * darkness_score) + 
               (W_HIGHWAY * highway_risk) + (W_LAND * land_risk)
```
- **W_CURVE**: 10.0 - Road curvature/sinuosity
- **W_DARKNESS**: 30.0 - Lack of streetlights
- **W_HIGHWAY**: 40.0 - Road type (motorway safer, residential less)
- **W_LAND**: 20.0 - Land use type

### New (Walking Routes) - graph_builder.py
```
safety_score = (W_DARKNESS * darkness_score) + (W_SIDEWALK * sidewalk_score) + 
               (W_BUSINESS * business_score) + (W_LAND * (1 - land_risk))
```
- **W_DARKNESS**: 40.0 - Streetlight coverage (higher weight for pedestrian visibility)
- **W_SIDEWALK**: 30.0 - Sidewalk availability (critical for safe walking)
- **W_BUSINESS**: 15.0 - Proximity to open businesses (populated areas feel safer)
- **W_LAND**: 15.0 - Land use type (less critical for walking)

### Key Improvements
1. **Removed**: Curvature/sinuosity scoring (irrelevant for pedestrians choosing between routes)
2. **Added**: Sidewalk availability scoring (critical safety factor for pedestrians)
3. **Added**: Business proximity scoring (pedestrians prefer populated, well-monitored areas)
4. **Updated**: Highway type function renamed from `highway_risk_from_tag()` to `get_pedestrian_street_type_score()` with pedestrian-friendly scoring

### New Data Integration
- **Sidewalk Score**: 1.0 (dedicated sidewalk) → 0.8 (sidewalk one side) → 0.3 (no sidewalk) → 0.5 (default)
- **Business Score**: 0.9 (nearby businesses) → 0.4 (isolated) → 0.5 (default)
- **Land Risk**: Inverted from the driving algorithm (1 - land_risk to penalize risky areas)

---

## 3. User Interface Updates

### web/templates/index.html

#### 3.1 Branding Changes
- **Header**: "🌟 LitRoutes" → "🚶 LitWalks"
- **Tagline**: "Find the safest route, not just the fastest" → "Find the safest walking routes in your city"
- **Page Title**: "LitRoutes - Safe Route Visualization" → "LitWalks - Safe Walking Route Finder"

#### 3.2 New Controls
- **Departure Time Input**: Added `<input type="datetime-local" id="departureTimeInput" />`
  - Allows users to specify when they plan to walk
  - Can be used in future to account for business hours and lighting variations
  - "Now" button to quickly set current time
  - Default: Set to current time on page load

#### 3.3 Map Layers Updated
- **Removed**: "🚧 Road Safety Data" (not relevant for pedestrians)
- **Kept**: "💡 Streetlights" (critical for pedestrian safety)
- **Added**: "🚶 Sidewalk Coverage" (pedestrian infrastructure)
- **Added**: "🏪 Open Businesses" (populated areas)

#### 3.4 Results Display
- **Changed from**: "Fastest Route" / "Safest Route" comparison
- **Changed to**: Single "Safe Route" recommendation with walking metrics
- **Metrics shown**:
  - Distance (in miles)
  - Walking Time
  - Safety Score
  - Streetlights % coverage
  - Sidewalk Coverage %
  - Nearby Businesses count

#### 3.5 Route Computation Button
- **Changed**: "🚗 Compare Routes" → "🚶 Find Safe Walking Route"
- **Behavior**: Now returns single recommended route optimized for pedestrian safety

---

## 4. Frontend JavaScript Updates

### web/static/app.js

#### 4.1 Departure Time Handling
- Added event listener for "Now" button: Sets departure time to current time
- Default departure time: Set to current time on page load
- Departure time is now sent to backend with route computation request

#### 4.2 Route Display Logic
- **Old**: Displayed two routes (fastest in magenta, safest in cyan)
- **New**: Displays single recommended walking route in green
- Route popup: "🛡️ Recommended Walking Route" (instead of "Safest Route")

#### 4.3 Results Panel Updates
- Updated to display walking-specific metrics instead of driving metrics
- Results display adapts to show:
  - Single route recommendation
  - Lighting conditions
  - Sidewalk availability
  - Business proximity

#### 4.4 Layer Toggle Handling
- Updated to handle new layer toggles (sidewalks, businesses)
- Made code more robust with fallback checks for missing elements

#### 4.5 Route Computation Request
- Now includes `departure_time` field in POST request body
- Format: ISO 8601 datetime string

---

## 5. Backend API Changes

### web_app.py

#### 5.1 Route Computation Endpoint (`/api/routes`)
- **Added**: Support for `departure_time` parameter in request
- **Doc Update**: Updated docstring to emphasize walking routes
- **Behavior**: Continues to compute both fastest and safest routes
  - Frontend treats "safest" as the recommended walking route
  - "Fastest" is provided as fallback but not prominently displayed

#### 5.2 Response Format
Response structure remains the same for backward compatibility:
```json
{
  "status": "success",
  "start": {"lat": ..., "lon": ...},
  "end": {"lat": ..., "lon": ...},
  "fastest": {"geojson": ..., "data": {...}},
  "safest": {"geojson": ..., "data": {...}}
}
```

---

## 6. Configuration Updates

### Safety Scoring Weights (graph_builder.py)
```python
# Walking routes focus on pedestrian-specific factors
W_DARKNESS = 40.0      # Streetlight coverage (most important)
W_SIDEWALK = 30.0      # Sidewalk availability (critical)
W_BUSINESS = 15.0      # Proximity to open businesses
W_LAND = 15.0          # Land use characteristics
```

### API Endpoints
- `/api/routes` - Now processes walking route requests with optional departure_time
- `/api/graph-data` - Returns graph with walking-focused safety scores
- `/api/graph-data-lite` - Sampled graph with walking safety metrics

---

## 7. Data Flow Diagram

### Route Computation Flow
```
User Input (Start, End, Departure Time)
        ↓
Parse/Geocode Locations
        ↓
Snap to Graph Nodes
        ↓
Fetch Additional Data:
  ├─ Streetlight locations (Duke Energy API)
  ├─ Sidewalk coverage (Overpass API)
  └─ Open businesses (Overpass API)
        ↓
Score Edges with Walking Metrics:
  ├─ Darkness score (lights per meter)
  ├─ Sidewalk score (infrastructure availability)
  ├─ Business score (proximity to populated areas)
  └─ Land risk score (environment type)
        ↓
Compute Safest Path (NetworkX)
        ↓
Return Route as GeoJSON + Metrics
        ↓
Display on Map with Walking-Focused Information
```

---

## 8. Future Enhancements

### Planned Features
1. **Business Hours Integration**: Use departure_time to filter only open businesses
2. **Time-Based Lighting**: Account for sunset/sunrise times in darkness scoring
3. **Crime Data**: Integrate local crime statistics if available
4. **Accessibility**: Add wheelchair accessibility indicators
5. **Route Preferences**: Allow users to prefer well-lit routes, highly populated areas, etc.
6. **Weather Integration**: Account for weather conditions in route safety
7. **Historical Data**: Use historical foot traffic patterns for area safety scoring

### Database Enhancements
- Store user routes and feedback for ML-based safety improvements
- Track which routes users actually take vs recommended
- Build community-driven safety ratings

---

## 9. Testing Recommendations

### Unit Tests
- [ ] `fetch_open_businesses()` with various bboxes
- [ ] `fetch_sidewalk_coverage()` data parsing
- [ ] Walking safety score calculation with various metrics
- [ ] Frontend departure time handling

### Integration Tests
- [ ] Complete route computation with all new data sources
- [ ] Verify graph edge scoring includes sidewalk/business data
- [ ] Test with various start/end points in service area
- [ ] Verify GeoJSON output includes new metrics

### UI/UX Tests
- [ ] Departure time picker functionality
- [ ] Layer toggle behavior for sidewalks/businesses
- [ ] Results display shows all walking metrics
- [ ] Route coloring and styling on map

### Performance Tests
- [ ] Overpass API query performance with caching
- [ ] Graph building time with new scoring functions
- [ ] Route computation performance with safety weights
- [ ] Memory usage with business/sidewalk data loaded

---

## 10. Deployment Notes

### Dependencies
- New or updated: `requests` (for Overpass API calls)
- Existing: All other dependencies remain the same

### Cache Files
- New cache files will be created automatically on first use
- Sidewalk cache: 24-hour TTL
- Business cache: 1-hour TTL
- Pre-existing Duke and NLCD caches remain functional

### Backward Compatibility
- Web API response format unchanged
- Graph structure unchanged
- Existing routes will work with new scoring algorithm

### Migration Path
1. Deploy new data_fetcher functions
2. Update graph_builder imports
3. Re-run `build_graph_offline.py` to generate new graph with walking scores
4. Deploy frontend changes
5. Monitor Overpass API usage (free tier: ~10,000 queries/day)

---

## Conclusion

The application has been successfully transitioned from a driving-focused route planner to a pedestrian-focused one. The new safety scoring algorithm prioritizes factors critical to pedestrians (lighting, sidewalks, populated areas) while removing irrelevant metrics (road curvature). Enhanced data sources and an updated UI provide users with comprehensive information for safe walking route selection.
