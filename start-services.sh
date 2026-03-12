#!/bin/bash

# Start services with proper logging
cd /home/ubuntu/boe-project

echo "Starting API Server..."
# Set PYTHONPATH to include the api directory
export PYTHONPATH=/home/ubuntu/boe-project/api:$PYTHONPATH
nohup /home/ubuntu/boe-project/new_venv/bin/python -m uvicorn api_server:app --host 0.0.0.0 --port 8000 > api.log 2>&1 &
API_PID=$!
echo "API Server started with PID: $API_PID"

echo "Starting Streamlit Server..."
nohup /home/ubuntu/boe-project/new_venv/bin/streamlit run frontend/Home.py --server.address 0.0.0.0 --server.port 8501 > streamlit.log 2>&1 &
STREAMLIT_PID=$!
echo "Streamlit Server started with PID: $STREAMLIT_PID"

# Save PIDs for monitoring
echo $API_PID > api.pid
echo $STREAMLIT_PID > streamlit.pid

echo "Services started!"
echo "API Log: /home/ubuntu/boe-project/api.log"
echo "Streamlit Log: /home/ubuntu/boe-project/streamlit.log"

# Wait a moment and check if services are running
sleep 3
echo "Checking service status..."
if ps -p $API_PID > /dev/null; then
    echo "✅ API Server is running"
else
    echo "❌ API Server failed to start"
    echo "Check api.log for errors"
fi

if ps -p $STREAMLIT_PID > /dev/null; then
    echo "✅ Streamlit Server is running"
else
    echo "❌ Streamlit Server failed to start"
    echo "Check streamlit.log for errors"
fi
