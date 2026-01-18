# LitRoutes - Safe Route Visualization

A web-based application that compares the fastest route vs. the safest route between two locations. Routes are optimized based on street lighting availability and road curvature data.

## Features

- 🗺️ **Interactive Map**: View road networks colored by safety score
- ⚡ **Fastest Route**: Optimized for travel time using OSRM routing
- 🛡️ **Safest Route**: Optimized considering street lights and road curvature
- 💡 **Streetlight Visualization**: See Duke Energy streetlights on the map
- 📍 **Address Geocoding**: Search by address or click on the map
- 📊 **Route Comparison**: Compare distance, time, and safety metrics

## Local Development

### Prerequisites

- Python 3.9+
- pip (Python package manager)

### Setup

1. **Install dependencies**:
```bash
pip install -r requirements.txt
```

2. **Run the web server**:
```bash
python web_app.py
```

3. **Open in browser**:
Visit `http://localhost:5000`

### Usage

1. Enter a starting address/location or click the 📍 button and click on the map
2. Enter a destination address/location or click the 📍 button and click on the map
3. Click "Compare Routes" button
4. View the results:
   - **⚡ Fastest Route** (yellow dashed line): Optimized for speed
   - **🛡️ Safest Route** (blue solid line): Optimized for safety with lights
5. See detailed metrics: distance, travel time, speed, and safety score

### Map Legend

- 🔵 **Blue roads**: Safe (low safety score)
- 🟡 **Yellow roads**: Medium risk
- 🔴 **Red roads**: High risk (curvy, dark, high speed)
- 💛 **Yellow dots**: Duke Energy streetlights
- 🟢 **Green marker**: Start point
- 🔴 **Red marker**: End point

## Deployment

### Docker (Recommended for Production)

1. **Build and run with Docker Compose**:
```bash
docker-compose up -d
```

2. **Access the application**:
Open `http://localhost:5000` in your browser

3. **Stop the application**:
```bash
docker-compose down
```

### Manual Docker Build

```bash
# Build the image
docker build -t litroutes:latest .

# Run the container
docker run -p 5000:5000 \
  -v $(pwd)/cache:/app/cache \
  -v $(pwd)/duke_cache.json:/app/duke_cache.json \
  litroutes:latest
```

### Cloud Deployment Options

#### Heroku
```bash
# Install Heroku CLI
# Login to Heroku
heroku login

# Create app
heroku create your-litroutes-app

# Deploy
git push heroku main

# Open in browser
heroku open
```

#### AWS (using EC2 + Docker)
1. Launch an EC2 instance
2. Install Docker and Docker Compose
3. Clone this repository
4. Run `docker-compose up -d`
5. Configure security groups to allow port 5000/5 (or use reverse proxy like Nginx)

#### Railway.app (Simple)
1. Connect your GitHub repository to Railway
2. Add environment variables if needed
3. Deploy automatically on push

#### Render.com
1. Connect repository
2. Set build command: `pip install -r requirements.txt`
3. Set start command: `python web_app.py`
4. Deploy

### Environment Variables

- `FLASK_ENV`: Set to `production` for production deployments
- `PORT`: Port to run the server (default: 5000)

## Architecture

### Backend (Python/Flask)
- `web_app.py`: Main Flask application with API endpoints
- `graph_builder.py`: Builds road network graph and computes safety scores
- `data_fetcher.py`: Fetches Duke Energy streetlight data
- `route_visualizer.py`: Contains route computation logic

### Frontend (HTML/CSS/JavaScript)
- `web/templates/index.html`: Main page layout
- `web/static/style.css`: Styling
- `web/static/app.js`: Leaflet map integration and route computation

### API Endpoints

- `GET /`: Main web interface
- `GET /api/health`: Health check
- `GET /api/graph-data`: Get road network and streetlights as GeoJSON
- `POST /api/routes`: Compute fastest and safest routes
  - Request body:
    ```json
    {
      "start": "[lat, lon]" or "address string",
      "end": "[lat, lon]" or "address string"
    }
    ```
  - Response:
    ```json
    {
      "status": "success",
      "start": {"lat": 35.xxx, "lon": -82.xxx},
      "end": {"lat": 35.xxx, "lon": -82.xxx},
      "fastest": {
        "geojson": {...},
        "data": {"distance_m": 1000, "travel_time_s": 60, "avg_speed_kmh": 60}
      },
      "safest": {
        "geojson": {...},
        "data": {"distance_m": 1200, "travel_time_s": 70, "safety_score": 500}
      }
    }
    ```

## How Safety Scores Work

The safety score is calculated based on:

1. **Base Risk**: 100 (baseline for all roads)
2. **Streetlights**: -90 (roads with Duke lights are much safer)
3. **Curvature Penalty**: Sinuous roads (ratio > 1.15) get a penalty
4. **Speed Penalty**: High-speed roads (>50 km/h) get a penalty
5. **Final Range**: 0-150 (lower is safer)

## Data Sources

- **Street Network**: OpenStreetMap (via OSMnx)
- **Routing**: OSRM (Open Source Routing Machine) - public server
- **Streetlights**: Duke Energy API
- **Geocoding**: OpenStreetMap Nominatim

## Troubleshooting

### "Could not geocode address"
- Try using a simpler format: "Street, City, State"
- Or use coordinates directly: "35.4567, -82.5678"

### "No path found"
- Start and end points may not be connected in the graph
- Try points further apart or in different areas

### Map not loading
- Check browser console for errors (F12 → Console)
- Ensure internet connection (maps require Leaflet CDN)

### Slow route computation
- First computation builds the entire graph (can take 1-2 minutes)
- Subsequent requests use cached graph and are faster
- For large areas, consider reducing BBOX size

## Performance Tips

1. **Caching**: The road network graph is cached in memory after first use
2. **Data Caching**: Duke lights are cached locally in `duke_cache.json`
3. **Browser Caching**: Maps and static assets are cached by browser
4. **Async Loading**: Map data loads asynchronously without blocking UI

## Future Enhancements

- [ ] Real-time traffic data integration
- [ ] Multiple routing algorithms comparison
- [ ] Route sharing and bookmarking
- [ ] Historical crime data overlay
- [ ] Weather and visibility consideration
- [ ] User preferences and profiles
- [ ] Mobile app (React Native)
- [ ] Multi-stop route optimization
- [ ] Distance matrix API
- [ ] Route elevation profile

## License

MIT License - See LICENSE file for details

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Support

For issues, questions, or suggestions:
- Open an issue on GitHub
- Check existing issues for solutions
- Contact the development team

## Data Attribution

- OpenStreetMap contributors
- Duke Energy
- OSRM routing engine
- Mapillary (for future street view integration)
