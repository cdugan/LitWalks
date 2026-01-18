#!/bin/bash

# LitRoutes Web Application Startup Script
# For Linux/Mac users

set -e

echo "=========================================="
echo "LitRoutes Web Application Setup"
echo "=========================================="
echo ""

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed"
    echo "Please install Python 3.9 or higher"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "✓ Python $PYTHON_VERSION detected"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -q -r requirements.txt

echo ""
echo "=========================================="
echo "🌟 Starting LitRoutes Web Application"
echo "=========================================="
echo ""
echo "📍 Server running at: http://localhost:5000"
echo "🌐 Open your browser and navigate to http://localhost:5000"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

# Run the application
python web_app.py
