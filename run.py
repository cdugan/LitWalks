#!/usr/bin/env python
"""
LitRoutes Web Application Startup Script

This script checks dependencies and starts the web server.
"""

import sys
import subprocess
import os

def check_python_version():
    """Check if Python version is 3.9 or higher."""
    if sys.version_info < (3, 9):
        print(f"❌ Python 3.9+ required, but you have {sys.version_info.major}.{sys.version_info.minor}")
        sys.exit(1)
    print(f"✓ Python {sys.version_info.major}.{sys.version_info.minor} detected")

def check_dependencies():
    """Check if required packages are installed."""
    required_packages = [
        'flask',
        'networkx',
        'osmnx',
        'geopy',
        'requests'
        # 'matplotlib'
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"✓ {package} installed")
        except ImportError:
            missing.append(package)
            print(f"❌ {package} NOT installed")
    
    if missing:
        print(f"\n⚠️  Missing packages: {', '.join(missing)}")
        print(f"\nRun: pip install -r requirements.txt")
        response = input("\nInstall now? (y/n): ")
        if response.lower() == 'y':
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])
        else:
            sys.exit(1)

def start_server():
    """Start the Flask development server."""
    print("\n" + "="*60)
    print("🌟 Starting LitRoutes Web Application")
    print("="*60)
    print("\n📍 Server running at: http://localhost:5000")
    print("🌐 Open your browser and navigate to http://localhost:5000")
    print("\nPress Ctrl+C to stop the server\n")
    
    try:
        from web_app import app
        app.run(debug=True, host='0.0.0.0', port=5000)
    except Exception as e:
        print(f"\n❌ Error starting server: {e}")
        sys.exit(1)

if __name__ == '__main__':
    print("\n" + "="*60)
    print("LitRoutes Web Application Setup")
    print("="*60 + "\n")
    
    # Check Python version
    check_python_version()
    print()
    
    # Check dependencies
    check_dependencies()
    print()
    
    # Start server
    start_server()
