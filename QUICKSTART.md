# Quick Start Guide - LitRoutes Web Application

## 🚀 Get Started in 5 Minutes

### Option 1: Simple Python (Recommended for Development)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the application
python web_app.py

# 3. Open your browser
# Visit: http://localhost:5000
```

### Option 2: Docker (Recommended for Production)

```bash
# 1. Build and run
docker-compose up -d

# 2. Open your browser
# Visit: http://localhost:5000

# 3. Stop when done
docker-compose down
```

### Option 3: Using the Startup Script

```bash
# Run the startup script (handles dependency checking)
python run.py
```

## 📍 Using the Application

1. **Enter Start Location**:
   - Type an address (e.g., "123 Main St, Durham, NC")
   - Or click the 📍 button and click on the map
   - Or use coordinates (e.g., "35.9940, -78.8986")

2. **Enter End Location**:
   - Same options as start location

3. **Click "Compare Routes"**:
   - The app will compute two routes:
     - **⚡ Fastest Route** (yellow dashed)
     - **🛡️ Safest Route** (blue solid)

4. **Review Results**:
   - See distance, time, and safety metrics
   - Click routes on map for details
   - Click streets to see lighting and curvature info

## 🌐 Accessing from Other Computers

If running on a server, access it from other machines:

```
http://<server-ip-address>:5000
```

For example:
```
http://192.168.1.100:5000
```

## 🔧 Troubleshooting

### Port Already in Use
If port 5000 is in use, modify `web_app.py`:
```python
app.run(debug=True, host='0.0.0.0', port=5001)  # Use 5001 instead
```

### Address Not Geocoding
Try simpler formats:
- ❌ "1000 Main Street, Durham, North Carolina, 27701"
- ✓ "Main St, Durham, NC"
- ✓ "Durham, NC"

### Map Not Showing Routes
- Check browser console for errors (F12)
- Ensure you have internet (map uses Leaflet CDN)
- Try different start/end points

## 📊 System Requirements

- Python 3.9+
- 2GB+ RAM (for loading street network)
- Internet connection (for maps and geocoding)

## 🚢 Deploying to Production

See [README_WEB.md](README_WEB.md) for detailed deployment instructions including:
- Docker containerization
- Cloud platforms (Heroku, AWS, Railway, Render)
- Nginx reverse proxy setup
- SSL/HTTPS configuration

## 💡 Tips for Best Experience

1. **Caching**: First load builds the graph (1-2 min). Subsequent loads are faster.
2. **Zoom**: Use mouse wheel to zoom, drag to pan
3. **Route Details**: Click on routes or roads to see detailed information
4. **Shortcuts**: Press Enter after typing address to compute routes

## 📞 Getting Help

- Check the main [README_WEB.md](README_WEB.md)
- Review error messages in browser console (F12)
- Check server logs in terminal for detailed errors

Happy routing! 🗺️✨
