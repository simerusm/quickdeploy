#!/bin/bash
# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get the absolute path to the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo "Script is running from: ${SCRIPT_DIR}"

# Set directories relative to script location
INSTALL_DIR="${SCRIPT_DIR}"
LOG_DIR="${INSTALL_DIR}/logs"
API_DIR="${INSTALL_DIR}/src/api"
DASHBOARD_DIR="${INSTALL_DIR}/src/dashboard"

# Create necessary directories
echo -e "${GREEN}Creating necessary directories...${NC}"
mkdir -p "${LOG_DIR}"
mkdir -p "${API_DIR}"
mkdir -p "${DASHBOARD_DIR}"

echo -e "${GREEN}Starting QuickDeploy services...${NC}"

# Check if your Python files exist
if [ ! -f "${API_DIR}/app.py" ]; then
  echo -e "${RED}API file not found: ${API_DIR}/app.py${NC}"
  exit 1
fi

if [ ! -f "${API_DIR}/worker.py" ]; then
  echo -e "${RED}Worker file not found: ${API_DIR}/worker.py${NC}"
  exit 1
fi

if [ ! -f "${DASHBOARD_DIR}/dashboard.py" ]; then
  echo -e "${RED}Dashboard file not found: ${DASHBOARD_DIR}/dashboard.py${NC}"
  exit 1
fi

# Start API
echo -e "${GREEN}Starting API service...${NC}"
cd "${API_DIR}"
python3 app.py > "${LOG_DIR}/api.log" 2>&1 &
API_PID=$!
sleep 2
if ps -p $API_PID > /dev/null; then
  echo -e "${GREEN}API service started (PID: $API_PID)${NC}"
else
  echo -e "${RED}Failed to start API service. Check logs at ${LOG_DIR}/api.log${NC}"
  if [ -f "${LOG_DIR}/api.log" ]; then
    tail -n 20 "${LOG_DIR}/api.log"
  else
    echo -e "${RED}Log file not created${NC}"
  fi
fi

# Start worker (now in the same directory as API)
echo -e "${GREEN}Starting build worker...${NC}"
cd "${API_DIR}"
python3 worker.py > "${LOG_DIR}/worker.log" 2>&1 &
WORKER_PID=$!
sleep 2
if ps -p $WORKER_PID > /dev/null; then
  echo -e "${GREEN}Build worker started (PID: $WORKER_PID)${NC}"
else
  echo -e "${RED}Failed to start build worker. Check logs at ${LOG_DIR}/worker.log${NC}"
  if [ -f "${LOG_DIR}/worker.log" ]; then
    tail -n 20 "${LOG_DIR}/worker.log"
  else
    echo -e "${RED}Log file not created${NC}"
  fi
fi

# Start dashboard
echo -e "${GREEN}Starting web dashboard...${NC}"
cd "${DASHBOARD_DIR}"
python3 dashboard.py > "${LOG_DIR}/dashboard.log" 2>&1 &
DASHBOARD_PID=$!
sleep 2
if ps -p $DASHBOARD_PID > /dev/null; then
  echo -e "${GREEN}Web dashboard started (PID: $DASHBOARD_PID)${NC}"
else
  echo -e "${RED}Failed to start web dashboard. Check logs at ${LOG_DIR}/dashboard.log${NC}"
  if [ -f "${LOG_DIR}/dashboard.log" ]; then
    tail -n 20 "${LOG_DIR}/dashboard.log"
  else
    echo -e "${RED}Log file not created${NC}"
  fi
fi

# Set up port forwarding for ingress controller
echo -e "${GREEN}Setting up port forwarding for ingress access...${NC}"
kubectl port-forward -n ingress-nginx service/ingress-nginx-controller 8090:80 > "${LOG_DIR}/ingress.log" 2>&1 &
INGRESS_PID=$!
sleep 2
if ps -p $INGRESS_PID > /dev/null; then
  echo -e "${GREEN}Ingress port forwarding started (PID: $INGRESS_PID)${NC}"
else
  echo -e "${RED}Failed to start ingress port forwarding. Check logs at ${LOG_DIR}/ingress.log${NC}"
  if [ -f "${LOG_DIR}/ingress.log" ]; then
    tail -n 20 "${LOG_DIR}/ingress.log"
  else
    echo -e "${RED}Log file not created${NC}"
  fi
fi

echo -e "\n${GREEN}QuickDeploy services:${NC}"
echo -e "- API: http://localhost:8000"
echo -e "- Dashboard: http://localhost:8080"
echo -e "- Deployments: http://app-*.quickdeploy.local:8090"
echo -e "\nPress Ctrl+C to stop all services"

# Function to kill processes safely
function cleanup {
  echo -e "${YELLOW}Stopping QuickDeploy services...${NC}"
  
  if ps -p $API_PID > /dev/null; then kill $API_PID; fi
  if ps -p $WORKER_PID > /dev/null; then kill $WORKER_PID; fi
  if ps -p $DASHBOARD_PID > /dev/null; then kill $DASHBOARD_PID; fi
  if ps -p $INGRESS_PID > /dev/null; then kill $INGRESS_PID; fi
  
  echo -e "${GREEN}Services stopped${NC}"
  exit 0
}

# Handle clean shutdown
trap cleanup INT TERM

# Keep script running
wait