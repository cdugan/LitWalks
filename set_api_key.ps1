# Set your Google Places API key here and run this script before build_graph_offline.py
# Usage: Set the API key below, then run:
#   . .\set_api_key.ps1
#   python build_graph_offline.py

$env:GOOGLE_PLACES_API_KEY = "YOUR_API_KEY_HERE"

Write-Host "Google Places API Key set for this PowerShell session"
Write-Host "Now run: python build_graph_offline.py"
