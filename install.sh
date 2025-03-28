#!/bin/bash
# QuickDeploy Installation Script for macOS with Docker Desktop Kubernetes

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}===== QuickDeploy Installation Script for macOS =====${NC}"
echo "This script will install QuickDeploy and its dependencies."

# Check for required commands
echo -e "\n${GREEN}Checking for required commands...${NC}"
commands=("git" "curl" "docker" "python3" "pip3" "kubectl")
missing=()

for cmd in "${commands[@]}"; do
  if ! command -v $cmd &> /dev/null; then
    missing+=($cmd)
  fi
done

if [ ${#missing[@]} -ne 0 ]; then
  echo -e "${YELLOW}Missing dependencies: ${missing[*]}${NC}"
  
  echo -e "${YELLOW}Installing missing dependencies using Homebrew...${NC}"
  
  # Check if Homebrew is installed
  if ! command -v brew &> /dev/null; then
    echo -e "${YELLOW}Installing Homebrew...${NC}"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  fi
  
  # Install dependencies
  for cmd in "${missing[@]}"; do
    case $cmd in
      "git")
        brew install git
        ;;
      "curl")
        brew install curl
        ;;
      "docker")
        echo -e "${YELLOW}Please install Docker Desktop from https://www.docker.com/products/docker-desktop${NC}"
        echo -e "${YELLOW}After installation, enable Kubernetes in Docker Desktop Settings.${NC}"
        exit 1
        ;;
      "python3")
        brew install python
        ;;
      "pip3")
        brew install python # This will also install pip
        ;;
      "kubectl")
        brew install kubectl
        ;;
    esac
  done
fi

# Check if Docker Desktop Kubernetes is running
if ! kubectl get nodes &> /dev/null; then
  echo -e "${YELLOW}Kubernetes not running. Please ensure Docker Desktop is running with Kubernetes enabled.${NC}"
  echo -e "${YELLOW}1. Open Docker Desktop${NC}"
  echo -e "${YELLOW}2. Go to Settings > Kubernetes${NC}"
  echo -e "${YELLOW}3. Check 'Enable Kubernetes'${NC}"
  echo -e "${YELLOW}4. Click 'Apply & Restart'${NC}"
  echo -e "${YELLOW}5. Run this script again after Kubernetes is running${NC}"
  exit 1
fi

# Create installation directory
INSTALL_DIR="."
echo -e "\n${GREEN}Creating installation directory...${NC}"
mkdir -p $INSTALL_DIR
cd $INSTALL_DIR

# Set up local container registry
echo -e "\n${GREEN}Setting up local Docker registry...${NC}"
docker ps | grep -q registry:2
if [ $? -ne 0 ]; then
  docker run -d -p 5005:5000 --name registry registry:2
  echo -e "${GREEN}Local registry started${NC}"
else
  echo -e "${GREEN}Local registry already running${NC}"
fi

# Configure Docker for insecure registry if needed
if ! grep -q "localhost:5005" ~/Library/Group\ Containers/group.com.docker/settings.json 2>/dev/null; then
  echo -e "${YELLOW}Please add localhost:5005 to insecure-registries in Docker Desktop:${NC}"
  echo -e "${YELLOW}1. Open Docker Desktop${NC}"
  echo -e "${YELLOW}2. Go to Settings > Docker Engine${NC}"
  echo -e "${YELLOW}3. Add 'localhost:5005' to insecure-registries${NC}"
  echo -e "${YELLOW}4. Click 'Apply & Restart'${NC}"
fi

# Setup local DNS for .quickdeploy.local domains
echo -e "\n${GREEN}Setting up local DNS...${NC}"
if ! grep -q "quickdeploy.local" /etc/hosts; then
  echo -e "${YELLOW}Adding quickdeploy.local domains to /etc/hosts (requires sudo)${NC}"
  echo "127.0.0.1 quickdeploy.local" | sudo tee -a /etc/hosts > /dev/null
  echo "127.0.0.1 api.quickdeploy.local" | sudo tee -a /etc/hosts > /dev/null
  echo "127.0.0.1 dashboard.quickdeploy.local" | sudo tee -a /etc/hosts > /dev/null
  echo "127.0.0.1 registry.quickdeploy.local" | sudo tee -a /etc/hosts > /dev/null
fi

# Set up Redis
echo -e "\n${GREEN}Setting up Redis...${NC}"
docker ps | grep -q redis:alpine
if [ $? -ne 0 ]; then
  docker run -d -p 6379:6379 --name redis redis:alpine
  echo -e "${GREEN}Redis started${NC}"
else
  echo -e "${GREEN}Redis already running${NC}"
fi

# Install Python requirements
echo -e "\n${GREEN}Installing Python dependencies...${NC}"
pip3 install fastapi uvicorn redis kubernetes flask requests tabulate rich

# Setup Kubernetes Nginx Ingress Controller
echo -e "\n${GREEN}Setting up Ingress Controller...${NC}"
if ! kubectl get namespace ingress-nginx &> /dev/null; then
  kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/cloud/deploy.yaml
  
  # Wait for ingress controller to be ready
  echo -e "${GREEN}Waiting for Ingress Controller to be ready...${NC}"
  kubectl wait --namespace ingress-nginx \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/component=controller \
    --timeout=120s
else
  echo -e "${GREEN}Ingress Controller already installed${NC}"
fi

# Create necessary directories
mkdir -p $INSTALL_DIR/src/{api,worker,dashboard/templates,cli}

# Create the Python files
echo -e "\n${GREEN}Creating QuickDeploy components...${NC}"

# Create the API service file
cat > $INSTALL_DIR/src/api/app.py << 'EOF'
# app.py file content will go here
EOF

# Create the worker file
cat > $INSTALL_DIR/src/worker/worker.py << 'EOF'
# worker.py file content will go here
EOF

# Create the dashboard file
cat > $INSTALL_DIR/src/dashboard/dashboard.py << 'EOF'
# dashboard.py file content will go here
EOF

# Create template directory and templates
mkdir -p $INSTALL_DIR/src/dashboard/templates

# Create the CLI tool
cat > $INSTALL_DIR/src/cli/quickdeploy.py << 'EOF'
# quickdeploy.py file content will go here
EOF
chmod +x $INSTALL_DIR/src/cli/quickdeploy.py

# Create symbolic link to CLI
echo -e "\n${GREEN}Creating CLI command...${NC}"
if [ ! -d "$HOME/bin" ]; then
  mkdir -p "$HOME/bin"
fi
ln -sf $INSTALL_DIR/src/cli/quickdeploy.py $HOME/bin/quickdeploy
echo 'export PATH="$HOME/bin:$PATH"' >> $HOME/.zshrc

# Create startup script
echo -e "\n${GREEN}Creating startup script...${NC}"
cat > $INSTALL_DIR/start.sh << 'EOF'
#!/bin/bash
# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

INSTALL_DIR="$HOME/quickdeploy"

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
EOF
chmod +x $INSTALL_DIR/start.sh

echo -e "\n${GREEN}Installation complete!${NC}"
echo -e "To start QuickDeploy, run: ${YELLOW}$INSTALL_DIR/start.sh${NC}"
echo -e "You can use the CLI with: ${YELLOW}quickdeploy${NC} (you may need to restart your terminal first)"