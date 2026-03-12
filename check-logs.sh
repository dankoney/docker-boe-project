#!/bin/bash

cd /home/ubuntu/boe-project

echo "=== Checking Running Processes ==="
ps aux | grep -E "(uvicorn|streamlit)" | grep -v grep

echo ""
echo "=== API Log (last 20 lines) ==="
if [ -f api.log ]; then
    tail -20 api.log
else
    echo "api.log not found"
fi

echo ""
echo "=== Streamlit Log (last 20 lines) ==="
if [ -f streamlit.log ]; then
    tail -20 streamlit.log
else
    echo "streamlit.log not found"
fi

echo ""
echo "=== Testing Services ==="
echo "API Server:"
if curl -s http://localhost:8000/health > /dev/null; then
    echo "✅ API is running"
else
    echo "❌ API is not responding"
fi

echo "Streamlit:"
if curl -s http://localhost:8501 > /dev/null; then
    echo "✅ Streamlit is running"
else
    echo "❌ Streamlit is not responding"
fi

echo ""
echo "=== External URLs ==="
echo "Frontend: http://51.20.84.10:8501"
echo "API: http://51.20.84.10:8000"
echo "API Docs: http://51.20.84.10:8000/docs"

echo ""
echo "=== Memory Usage ==="
free -h

echo ""
echo "=== Disk Usage ==="
df -h /home/ubuntu/boe-project
