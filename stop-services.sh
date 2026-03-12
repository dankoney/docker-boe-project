#!/bin/bash

cd /home/ubuntu/boe-project

echo "Stopping services..."

# Stop API Server
if [ -f api.pid ]; then
    API_PID=$(cat api.pid)
    if ps -p $API_PID > /dev/null; then
        kill $API_PID
        echo "Stopped API Server (PID: $API_PID)"
    else
        echo "API Server was not running"
    fi
    rm api.pid
else
    echo "API PID file not found, killing by process name"
    pkill -f "uvicorn api_server:app"
fi

# Stop Streamlit Server
if [ -f streamlit.pid ]; then
    STREAMLIT_PID=$(cat streamlit.pid)
    if ps -p $STREAMLIT_PID > /dev/null; then
        kill $STREAMLIT_PID
        echo "Stopped Streamlit Server (PID: $STREAMLIT_PID)"
    else
        echo "Streamlit Server was not running"
    fi
    rm streamlit.pid
else
    echo "Streamlit PID file not found, killing by process name"
    pkill -f "streamlit run frontend/Home.py"
fi

# Wait for processes to stop
sleep 2

# Force kill if still running
pkill -9 -f "uvicorn api_server:app" 2>/dev/null
pkill -9 -f "streamlit run frontend/Home.py" 2>/dev/null

echo "All services stopped!"
