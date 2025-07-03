#!/bin/bash

# BCS Secure Jeopardy Server Startup Script
# Usage: ./start_server.sh

set -e

echo "🎯 Starting BCS Secure Jeopardy Server..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📚 Installing dependencies..."
pip install -r requirements.txt

# Check server syntax
echo "🔍 Validating server code..."
python3 -m py_compile server.py

# Start the server
echo "🚀 Starting WebSocket server on port 9999..."
echo "📋 Server logs will be written to jeopardy_server.log"
echo "🌐 Access client at: http://localhost:8000/jeopardy.html"
echo "🎮 Access host panel at: http://localhost:8000/jeopardy_host.html"
echo "⚡ Press Ctrl+C to stop the server"
echo ""

python3 server.py