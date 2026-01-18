# Testing Plan for LitWalks Safe Walking Routes

## Overview
This document outlines comprehensive testing procedures to validate the transition from safe driving routes to safe walking routes.

---

## 1. Functional Testing

### 1.1 Data Fetching Functions

#### Test: Business Data Fetching
```python
# Test fetch_open_businesses function
bbox = (35.42, 35.28, -82.40, -82.55)  # Hendersonville area
businesses = fetch_open_businesses(bbox)

# Expected:
# - Returns list of tuples: (lat, lon, name, type)
# - Contains multiple business types (cafe, restaurant, shop, etc.)
# - Results are cached for 1 hour
```

**Validation Checklist**:
- [ ] Returns non-empty list for valid bbox
- [ ] Cache is created and used for subsequent calls within 1 hour
- [ ] Overpass API timeout handling works
- [ ] Cache file created at `businesses_cache.json`

#### Test: Sidewalk Coverage Fetching
```python
# Test fetch_sidewalk_coverage function
bbox = (35.42, 35.28, -82.40, -82.55)
sidewalk_data = fetch_sidewalk_coverage(bbox)

# Expected:
# - Returns dict mapping edge keys to sidewalk info
# - Each entry has: has_sidewalk, sidewalk_left, sidewalk_right
# - Results are cached for 24 hours
```

**Validation Checklist**:
- [ ] Returns dictionary with edge keys
- [ ] Each entry has required fields (has_sidewalk, sidewalk_left, sidewalk_right)
- [ ] Cache file created at `sidewalks_cache.json`
- [ ] 24-hour cache TTL respected

---

### 1.2 Safety Score Calculation

#### Test: Walking Safety Score Function
```python
# Test new safety scoring in graph_builder.py
# Build graph and verify edge attributes

for u, v, k, data in G.edges(keys=True, data=True):
    assert 'darkness_score' in data
    assert 'sidewalk_score' in data
    assert 'business_score' in data
    assert 'safety_score' in data
    assert 'land_risk' in data
    # Verify no curvature scoring
    assert 'curve_score' not in data
    assert 'highway_risk' not in data  # Old driving metric
```

**Validation Checklist**:
- [ ] Darkness score: 0-1 range (0=light, 1=dark)
- [ ] Sidewalk score: 0-1 range (0=none, 1=dedicated)
- [ ] Business score: 0-1 range (0=isolated, 1=busy)
- [ ] Land risk: 0-1 range (0=safe, 1=dangerous)
- [ ] Safety score: Weighted sum with new weights
- [ ] No curve_score or highway_risk in new graphs
- [ ] Old driving-focused metrics removed

---

### 1.3 Route Computation

#### Test: Single Safe Walking Route
```python
# Test API endpoint for walking route
start = {"address": "Downtown Hendersonville"}
end = {"address": "Main Street Park"}
departure_time = "2024-01-15T14:30:00Z"

response = POST /api/routes
{
    "start": start,
    "end": end,
    "departure_time": departure_time
}

# Expected:
# - Returns recommended walking route (safest path)
# - Route avoids dangerous areas
# - Route includes sidewalk-rich streets
# - Walking time calculated correctly
```

**Validation Checklist**:
- [ ] Departure time parameter accepted
- [ ] Single recommended route returned
- [ ] Route avoids motorways/highways (not for pedestrians)
- [ ] Route metrics include sidewalk coverage
- [ ] Route metrics include lighting coverage
- [ ] Route metrics include business proximity
- [ ] Walking time more realistic than driving time

---

## 2. UI/UX Testing

### 2.1 Departure Time Controls

#### Test: Time Picker Functionality
1. Load application at http://localhost:5000
2. Click departure time input field
3. Verify:
   - [ ] DateTime picker opens
   - [ ] Can select past, present, and future times
   - [ ] Format accepted: YYYY-MM-DDTHH:mm

#### Test: "Now" Button
1. Click "Now" button next to departure time input
2. Verify:
   - [ ] Current time populated in field
   - [ ] Format is correct (ISO 8601)
   - [ ] Button works repeatedly

#### Test: Default Time
1. Load page without any input
2. Verify:
   - [ ] Departure time field pre-populated with current time
   - [ ] Time is reasonable (within 1 minute of actual current time)

---

### 2.2 Map Layers

#### Test: Streetlights Layer Toggle
1. Open map
2. Toggle "💡 Streetlights" checkbox
   - [ ] Checked: Lights visible on map
   - [ ] Unchecked: Lights hidden from map
   - [ ] Toggle multiple times: Works consistently

#### Test: Sidewalk Coverage Layer Toggle
1. Open map
2. Toggle "🚶 Sidewalk Coverage" checkbox
   - [ ] Checkbox appears and is functional
   - [ ] Toggles sidewalk visualization on/off (when implemented)
   - [ ] No JavaScript errors in console

#### Test: Open Businesses Layer Toggle
1. Open map
2. Toggle "🏪 Open Businesses" checkbox
   - [ ] Checkbox appears and is functional
   - [ ] Toggles business markers on/off (when implemented)
   - [ ] No JavaScript errors in console

---

### 2.3 Results Display

#### Test: Walking Route Results
1. Enter start and end points
2. Click "🚶 Find Safe Walking Route"
3. Verify results panel shows:
   - [ ] Distance (in miles)
   - [ ] Walking Time (formatted as 15m 30s)
   - [ ] Safety Score (numerical value)
   - [ ] Streetlights % coverage
   - [ ] Sidewalk Coverage %
   - [ ] Nearby Businesses (count)

#### Test: Route Visualization
1. After computing route
2. Verify on map:
   - [ ] Route shown in green color
   - [ ] Route has white halo for visibility
   - [ ] Route connects start and end markers
   - [ ] Route avoids major roads where possible

---

## 3. Integration Testing

### 3.1 End-to-End Route Computation

#### Test Scenario 1: Downtown to Park
```
Start: Downtown Hendersonville
End: Main Street Park
Departure: 2024-01-15 14:30

Verify:
- Route computed successfully
- Route uses well-lit streets
- Route includes sidewalks
- Route passes near businesses
- Walking time is ~3-5 miles typical pace
```

#### Test Scenario 2: Residential Routes
```
Start: Residential neighborhood
End: Local coffee shop
Departure: 2024-01-15 20:00 (evening)

Verify:
- Route prioritizes streetlights (darker time)
- Route uses residential streets when available
- Route avoids isolated areas
- Safety score reflects lighting concerns at night
```

#### Test Scenario 3: Long Distance
```
Start: North neighborhood
End: South neighborhood
Departure: 2024-01-15 10:00

Verify:
- Route computed within reasonable time
- Memory usage stays reasonable
- Route is >1 mile, handles long distances
- Multiple business proximity changes along route
```

---

### 3.2 Data Source Integration

#### Test: Business Data in Routing
1. Generate route through downtown (many businesses)
2. Generate route through residential area (few businesses)
3. Verify:
   - [ ] Downtown route has higher business score
   - [ ] Downtown route scores as "safer" than residential
   - [ ] Safety scores differ based on business proximity

#### Test: Sidewalk Data in Routing
1. Generate route on streets with mapped sidewalks
2. Generate alternative route avoiding sidewalk streets
3. Verify:
   - [ ] Route with sidewalks has higher safety score
   - [ ] Safety scores favor sidewalk-equipped streets
   - [ ] Routing algorithm respects sidewalk weighting

---

## 4. Performance Testing

### 4.1 API Response Times

#### Test: Route Computation Speed
```
Measure times for various route lengths:
- Short (0.5 mi): Should complete in <2 seconds
- Medium (2 mi): Should complete in <5 seconds
- Long (5 mi): Should complete in <10 seconds
```

#### Test: Concurrent Requests
```
Send 5 simultaneous route requests
Verify:
- All complete successfully
- Response time increases <50%
- No race conditions
- Results are consistent
```

---

### 4.2 Memory Usage

#### Test: Memory During Route Computation
```
Monitor memory before/after route computation:
- Baseline: Note memory usage with just graph loaded
- After 10 routes: Check for memory leaks
- After 50 routes: Verify memory stable

Expected:
- Memory increases <20% per route
- Memory released after route completion
- No unbounded memory growth
```

---

### 4.3 Cache Performance

#### Test: Cache Hit Performance
```
1. Fetch businesses for bbox (cold cache): ~1-2 seconds
2. Fetch businesses for same bbox (warm cache): <100ms
3. Fetch sidewalks for bbox (cold cache): ~1-2 seconds
4. Fetch sidewalks for same bbox (warm cache): <100ms
```

---

## 5. Error Handling Testing

### 5.1 API Error Cases

#### Test: Invalid Start Location
```
POST /api/routes
{
    "start": "Invalid Place That Doesn't Exist",
    "end": "Main Street"
}

Expected:
- [ ] Error response returned
- [ ] Helpful error message
- [ ] HTTP 400 or 500 status code
```

#### Test: Out of Bounds Route
```
POST /api/routes
{
    "start": [35.42, -82.40],
    "end": [40.0, -75.0]  # Different city, out of bounds
}

Expected:
- [ ] Error response: location outside service area
- [ ] Clear error message
- [ ] No partial route returned
```

#### Test: No Route Found
```
POST /api/routes
{
    "start": [35.42, -82.40],
    "end": [35.4201, -82.4001]  # Very close, might be unreachable
}

Expected:
- [ ] Graceful error handling
- [ ] Error message: "No path found"
- [ ] No crash or timeout
```

---

### 5.2 External API Failures

#### Test: Overpass API Timeout
```
Simulate Overpass API timeout in fetch_open_businesses()

Verify:
- [ ] Function returns empty list (graceful degradation)
- [ ] No crash
- [ ] Route still computed without business data
- [ ] Error logged
```

#### Test: Overpass API Error
```
Simulate Overpass API returning 403/500 error

Verify:
- [ ] Function handles exception
- [ ] Returns empty list or cached data
- [ ] Route computation continues
- [ ] User informed if data unavailable
```

---

## 6. Data Quality Testing

### 6.1 Safety Score Distribution

#### Test: Score Range Validation
```
Analyze all edges in graph:
- darkness_score: All values between 0-1
- sidewalk_score: All values between 0-1  
- business_score: All values between 0-1
- safety_score: Reasonable range (0-100 estimated)
```

#### Test: Score Correlations
```
Verify logical relationships:
- High lighting (low darkness) → lower safety score component
- Has sidewalk → higher sidewalk score
- Near businesses → higher business score
- Residential areas → lower land risk
```

---

### 6.2 Route Quality Validation

#### Test: Route Preferences
1. Generate 10 different routes in various areas
2. Spot-check results:
   - [ ] All routes include proper sidewalk streets when available
   - [ ] Highly lit areas prioritized
   - [ ] Dense business areas included when safe
   - [ ] No routing through motorways/highways
   - [ ] Walking times reasonable (3-4 mph pace)

---

## 7. Browser Compatibility Testing

### 7.1 Frontend Functionality

Test in major browsers:
- [ ] Chrome/Edge 90+
- [ ] Firefox 88+
- [ ] Safari 14+

For each browser:
- [ ] All buttons functional
- [ ] DateTime picker works
- [ ] Map renders correctly
- [ ] Routes display
- [ ] No console errors

### 7.2 Mobile Testing

Test on mobile devices:
- [ ] UI responsive (not tested in this version, but good to note)
- [ ] Touch controls work
- [ ] DateTime picker mobile-friendly
- [ ] Map touch interactions work

---

## 8. Regression Testing

### 8.1 Existing Functionality

Verify previously working features still work:
- [ ] Map initialization
- [ ] Graph data loading
- [ ] Basic geocoding
- [ ] Route visualization
- [ ] Memory monitoring
- [ ] Health check endpoint

### 8.2 API Backward Compatibility

Verify API still accepts and returns expected formats:
- [ ] Response contains required fields
- [ ] GeoJSON format valid
- [ ] Distance/time calculations correct
- [ ] Coordinates in correct format

---

## 9. Test Execution Checklist

### Pre-Testing Setup
- [ ] Fresh installation or clean build
- [ ] Graph pre-built and ready (`build_graph_offline.py` run)
- [ ] Flask server running on http://localhost:5000
- [ ] Browser console open for error checking
- [ ] Network tab monitored for API calls

### During Testing
- [ ] Document any failures with screenshots
- [ ] Note performance metrics
- [ ] Record API response times
- [ ] Monitor error logs

### Post-Testing
- [ ] Compile all test results
- [ ] Flag critical issues (P0)
- [ ] Note minor issues (P1, P2)
- [ ] Verify all P0 issues resolved before release

---

## 10. Known Limitations & Future Tests

### Current Limitations
1. Overpass API has free tier limits (~10K queries/day)
2. Business hours not yet integrated
3. No real-time crime data
4. Time-based lighting not yet implemented

### Future Test Cases
- [ ] Business hours integration with departure_time
- [ ] Sunset/sunrise impact on lighting scores
- [ ] Crime statistics integration
- [ ] Historical foot traffic patterns
- [ ] Weather-aware route adjustments
- [ ] Accessibility (wheelchair) scoring
- [ ] Multi-modal routing (walk + transit)

---

## Test Results Summary Template

```
Test Date: _______________
Tester: ___________________
Build Version: ____________

Total Tests Run: __________
Passed: __________
Failed: __________
Blocked: __________

Critical Issues: 
- [List P0 issues]

Major Issues:
- [List P1 issues]

Minor Issues:
- [List P2 issues]

Sign-Off: ________________
```

---

## Conclusion

This comprehensive testing plan ensures the transition to safe walking routes is properly validated across all components: data sources, safety algorithms, UI/UX, API integration, performance, and error handling. All test cases should be executed before deploying to production.
