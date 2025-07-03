#!/bin/bash

# BCS Secure Jeopardy Server Startup Script
# Usage: ./start_server.sh [--local]
#        --local: Start server for local network play only (no ngrok)

set -e

LOCAL_ONLY=false

# Parse command line arguments
if [[ "$1" == "--local" ]]; then
    LOCAL_ONLY=true
fi

echo "🎯 Starting BCS Secure Jeopardy Server..."

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "🛑 Shutting down..."
    
    # Kill ngrok if it's running
    if [ ! -z "$NGROK_PID" ]; then
        echo "🔌 Stopping ngrok..."
        kill $NGROK_PID 2>/dev/null || true
    fi
    
    # Kill python server if it's running
    if [ ! -z "$SERVER_PID" ]; then
        echo "🔌 Stopping Python server..."
        kill $SERVER_PID 2>/dev/null || true
    fi
    
    # Deactivate virtual environment
    deactivate 2>/dev/null || true
    
    echo "👋 Goodbye!"
    exit 0
}

# Set up trap to cleanup on exit
trap cleanup EXIT INT TERM

# Check if ngrok is installed (only if not in local mode)
if [ "$LOCAL_ONLY" = false ] && ! command -v ngrok &> /dev/null; then
    echo "❌ ngrok is not installed. Please install it first:"
    echo "   brew install ngrok (on macOS)"
    echo "   or visit https://ngrok.com/download"
    echo ""
    echo "Or run in local mode with: ./start_server.sh --local"
    exit 1
fi

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

if [ "$LOCAL_ONLY" = false ]; then
    # Start ngrok in the background
    echo "🌐 Starting ngrok tunnel..."
    ngrok http 9999 --log-level=info --log=stdout > ngrok.log 2>&1 &
    NGROK_PID=$!

    # Wait a moment for ngrok to start
    echo "⏳ Waiting for ngrok to initialize..."
    sleep 3

    # Get the ngrok URL using the API
    NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | grep -o '"public_url":"[^"]*' | grep -o 'https://[^"]*' | head -1)

    if [ -z "$NGROK_URL" ]; then
        echo "❌ Failed to get ngrok URL. Please check ngrok.log for errors."
        exit 1
    fi

    # Extract just the hostname (remove https:// prefix)
    NGROK_HOST=$(echo $NGROK_URL | sed 's|https://||')

    # Extract the game ID from the hostname
    GAME_ID=$(echo $NGROK_HOST | grep -o '^[^.]*')
fi

# Start the Python server in the background
echo "🚀 Starting WebSocket server on port 9999..."
python3 server.py &
SERVER_PID=$!

# Display connection information
echo ""
echo "✅ Server is running!"

if [ "$LOCAL_ONLY" = false ]; then
    # Generate the join links
    JOIN_LINK="https://bcsjeopardy.com/?code=$GAME_ID"
    HOST_LINK="https://bcsjeopardy.com/host?code=$GAME_ID"
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🎮 GAME ID: $GAME_ID"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "📱 Players can join at: $JOIN_LINK"
    echo "🏠 Host panel: $HOST_LINK"
    echo ""
    echo "🌐 WebSocket URL: $NGROK_HOST"
    echo ""
else
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🏠 LOCAL NETWORK MODE"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "📱 Players on your network can connect using:"
    echo "   localhost:9999 (on this computer)"
    echo "   $(hostname -I | awk '{print $1}'):9999 (from other devices)"
    echo ""
fi

echo "🏠 Local access:"
echo "   Client: http://localhost:8000/jeopardy.html"
echo "   Host: http://localhost:8000/jeopardy_host.html"
echo ""
echo "📋 Server logs: jeopardy_server.log"
if [ "$LOCAL_ONLY" = false ]; then
    echo "📋 Ngrok logs: ngrok.log"
fi
echo ""
echo "⚡ Press Ctrl+C to stop the server"
echo ""

# Wait for the server to be stopped
wait $SERVER_PID