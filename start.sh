#!/bin/bash
# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

INSTALL_DIR="."

echo -e "${GREEN}Starting QuickDeploy services...${NC}"

# Check if Docker is running
if ! docker info &> /dev/null; then
  echo -e "${RED}Docker is not running. Please start Docker Desktop first.${NC}"
  exit 1
fi

# Check if Kubernetes is running
if ! kubectl get nodes &> /dev/null; then
  echo -e "${RED}Kubernetes is not running. Please enable Kubernetes in Docker Desktop.${NC}"
  exit 1
fi

# Make sure Redis is running
if ! docker ps | grep -q redis:alpine; then
  echo -e "${YELLOW}Starting Redis...${NC}"
  docker run -d -p 6379:6379 --name redis redis:alpine
fi

# Make sure registry is running
if ! docker ps | grep -q registry:2; then
  echo -e "${YELLOW}Starting container registry...${NC}"
  docker run -d -p 5005:5000 --name registry registry:2
fi

# Start API
echo -e "${GREEN}Starting API service...${NC}"
cd $INSTALL_DIR/src/api
python3 app.py &
API_PID=$!

# Start worker
echo -e "${GREEN}Starting build worker...${NC}"
cd $INSTALL_DIR/src/worker
python3 worker.py &
WORKER_PID=$!

# Start dashboard
echo -e "${GREEN}Starting web dashboard...${NC}"
cd $INSTALL_DIR/src/dashboard
python3 dashboard.py &
DASHBOARD_PID=$!

echo -e "${GREEN}All QuickDeploy services are running!${NC}"
echo -e "API: http://localhost:8000"
echo -e "Dashboard: http://localhost:8080"
echo -e "\nPress Ctrl+C to stop all services"

# Handle clean shutdown
trap "echo -e '${YELLOW}Stopping QuickDeploy services...${NC}'; kill $API_PID $WORKER_PID $DASHBOARD_PID; echo -e '${GREEN}Services stopped${NC}'; exit 0" INT TERM

wait
