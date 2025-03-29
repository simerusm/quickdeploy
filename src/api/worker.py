# worker.py - Build service worker for macOS with Docker Desktop Kubernetes
import redis
import json
import os
import re
import tempfile
import subprocess
import time
import sqlite3
import shutil
from kubernetes import client, config
from datetime import datetime
import socket
import logging

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("../../logs/worker.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("worker")

# Test logging
logger.info("Worker starting up")

# Connect to Redis
try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0)
    redis_client.ping()
    logger.info("Connected to Redis successfully")
except Exception as e:
    logger.error(f"Redis connection error: {e}")

# Load kubernetes config with fallback options
try:
    # Try loading from default kubeconfig file
    config.load_kube_config()
    logger.info("Loaded Kubernetes config from kubeconfig file")
except Exception as e:
    logger.error(f"Error loading kubeconfig: {e}")
    logger.info("Attempting to load in-cluster config")
    try:
        # Try in-cluster config as fallback
        config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config")
    except Exception as e:
        logger.error(f"Error loading in-cluster config: {e}")
        logger.warning("Kubernetes configuration failed!")

# Initialize Kubernetes API clients
v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()
networking_v1 = client.NetworkingV1Api()

def update_deployment_status(deployment_id, status, url=""):
    """Update deployment status in database"""
    try:
        conn = sqlite3.connect('quickdeploy.db')
        cursor = conn.cursor()
        updated_at = datetime.now().isoformat()
        cursor.execute(
            "UPDATE deployments SET status = ?, updated_at = ?, url = ? WHERE id = ?",
            (status, updated_at, url, deployment_id)
        )
        conn.commit()
        conn.close()
        logger.info(f"Updated deployment {deployment_id} status to {status}")
    except Exception as e:
        logger.error(f"Error updating deployment status: {e}")

def clone_repository(repo_url, branch, temp_dir):
    """Clone git repository to temporary directory"""
    try:
        # Check if it's a local file URL
        if repo_url.startswith("file://"):
            local_path = repo_url[7:]  # Remove "file://" prefix
            if os.path.isdir(local_path):
                # Copy files to temp directory
                for item in os.listdir(local_path):
                    source = os.path.join(local_path, item)
                    dest = os.path.join(temp_dir, item)
                    if os.path.isdir(source):
                        shutil.copytree(source, dest)
                    else:
                        shutil.copy2(source, dest)
                logger.info(f"Copied local directory {local_path} to {temp_dir}")
                return True
            else:
                logger.error(f"Local directory {local_path} does not exist")
                return False
        else:
            # Normal git clone
            logger.info(f"Cloning repository {repo_url} branch {branch}...")
            result = subprocess.run(
                ["git", "clone", "--branch", branch, repo_url, temp_dir],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE # stdout captured by pipe instead of printing to console
            )
            logger.info("Clone completed successfully")
            return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Git clone error: {e}")
        logger.error(f"Error output: {e.stderr.decode() if e.stderr else 'None'}")
        return False
    except Exception as e:
        logger.error(f"Clone error: {e}")
        return False
    
def detect_node_port(project_dir):
    """Detect the port a Node.js app will use"""
    try:
        with open(os.path.join(project_dir, "package.json")) as f:
            package_data = json.load(f)
        
        # First check for explicit port in custom scripts
        if "scripts" in package_data:
            for script_value in package_data["scripts"].values():
                port_match = re.search(r"-p\s*(\d+)|--port\s*(\d+)|PORT=(\d+)", script_value)
                if port_match:
                    port = next(p for p in port_match.groups() if p is not None)
                    return int(port)
        
        # Default ports by framework
        if "dependencies" in package_data:
            deps = package_data["dependencies"]
            if "next" in deps:
                return 3000  # Next.js default
            elif "nuxt" in deps:
                return 3000  # Nuxt.js default
            elif "express" in deps:
                return 3000  # Express common default
            elif "react-scripts" in deps:
                return 3000  # Create React App default
        
        # General Node.js default
        return 3000
    except Exception as e:
        logger.warning(f"Error detecting Node.js port: {e}")
        return 3000  # Default fallback
    
def detect_python_port(project_dir):
    """Detect the port a Python app will use"""
    try:
        # Look for common patterns in Python files
        for root, dirs, files in os.walk(project_dir):
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    with open(file_path, 'r') as f:
                        content = f.read()
                        
                        # Look for common port definitions
                        port_patterns = [
                            r'port\s*=\s*(\d+)',
                            r'PORT\s*=\s*(\d+)',
                            r'\.run\(.*port\s*=\s*(\d+)',
                            r'app\.run\(.*port\s*=\s*(\d+)'
                        ]
                        
                        for pattern in port_patterns:
                            match = re.search(pattern, content)
                            if match:
                                return int(match.group(1))
        
        # Default by framework detection
        if os.path.exists(os.path.join(project_dir, 'requirements.txt')):
            with open(os.path.join(project_dir, 'requirements.txt')) as f:
                req_content = f.read().lower()
                if 'flask' in req_content:
                    return 5000  # Flask default
                elif 'django' in req_content:
                    return 8000  # Django default
                elif 'fastapi' in req_content:
                    return 8000  # FastAPI default
        
        return 5000  # General Python default
    except Exception as e:
        logger.warning(f"Error detecting Python port: {e}")
        return 5000  # Default fallback

def detect_project_type(temp_dir):
    """Detect project type based on files, including subdirectories"""
    logger.info(f"Scanning directory: {temp_dir}")
    logger.debug(f"Root directory contents: {os.listdir(temp_dir)}")
    
    # Function to find files recursively
    def find_file(directory, target_file, max_depth=2, current_depth=0):
        if current_depth > max_depth:
            return None
            
        # Check current directory
        file_path = os.path.join(directory, target_file)
        if os.path.exists(file_path):
            return file_path
            
        # Check subdirectories
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            if os.path.isdir(item_path):
                # Skip node_modules, .git, etc.
                if item in ['node_modules', '.git', 'venv', '__pycache__']:
                    continue
                    
                found_path = find_file(item_path, target_file, max_depth, current_depth + 1)
                if found_path:
                    return found_path
                    
        return None
    
    # Check for package.json (Node.js)
    package_json_path = find_file(temp_dir, "package.json")
    if package_json_path:
        # Get the directory containing package.json
        project_dir = os.path.dirname(package_json_path)
        logger.info(f"Found package.json in {project_dir}")
        
        with open(package_json_path) as f:
            package_json = json.load(f)
        
        # Check for Next.js
        if "dependencies" in package_json and "next" in package_json["dependencies"]:
            logger.info("Detected project type: nextjs")
            return "nextjs", project_dir
        # Check for React
        elif "dependencies" in package_json and "react" in package_json["dependencies"]:
            logger.info("Detected project type: react")
            return "react", project_dir
        else:
            logger.info("Detected project type: nodejs")
            return "nodejs", project_dir
            
    # Check for requirements.txt (Python)
    requirements_path = find_file(temp_dir, "requirements.txt")
    if requirements_path:
        # Get the directory containing requirements.txt
        project_dir = os.path.dirname(requirements_path)
        logger.info(f"Found requirements.txt in {project_dir}")
        
        # Check for Django
        if os.path.exists(os.path.join(project_dir, "manage.py")):
            logger.info("Detected project type: django")
            return "django", project_dir
        # Check for Flask
        else:
            with open(requirements_path) as f:
                content = f.read().lower()
                if "flask" in content:
                    logger.info("Detected project type: flask")
                    return "flask", project_dir
                else:
                    logger.info("Detected project type: python")
                    return "python", project_dir
    
    logger.info("Detected project type: unknown")
    return "unknown", temp_dir

def detect_port(project_type, project_dir):
    """Detects the port of the project dynamically."""
    port = 80  # Default fallback port
    
    if project_type == "nextjs" or project_type == "react" or project_type == "nodejs":
        port = detect_node_port(project_dir)
    elif project_type == "flask" or project_type == "django" or project_type == "python":
        port = detect_python_port(project_dir)
    
    logger.info(f"Detected application port: {port}")
    
    return port

def build_project(project_type, project_dir, repo_dir, deployment_id):
    """Build project based on type"""
    try:
        port = detect_port(project_type, project_dir)

        if project_type == "nextjs":
            logger.info("Building Next.js project...")
            subprocess.run(["npm", "install"], cwd=project_dir, check=True)
            subprocess.run(["npm", "run", "build"], cwd=project_dir, check=True)
            
            # Create Dockerfile for Next.js
            with open(os.path.join(project_dir, "Dockerfile"), "w") as f:
                f.write("""
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install --production
COPY .next ./.next
COPY public ./public
COPY node_modules ./node_modules
CMD ["npm", "start"]
                """)
                
        elif project_type == "react":
            logger.info("Building React project...")
            subprocess.run(["npm", "install"], cwd=project_dir, check=True)
            subprocess.run(["npm", "run", "build"], cwd=project_dir, check=True)
            
            # Create Dockerfile for React
            with open(os.path.join(project_dir, "Dockerfile"), "w") as f:
                f.write("""
FROM nginx:alpine
COPY build /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
                """)
                
        elif project_type == "flask":
            logger.info("Building Flask project...")
            # Create virtual environment
            subprocess.run(["python3", "-m", "venv", "venv"], cwd=project_dir, check=True)
            
            # Install requirements
            if os.name == 'nt':  # Windows
                pip_path = os.path.join(project_dir, "venv", "Scripts", "pip")
            else:  # Unix-like
                pip_path = os.path.join(project_dir, "venv", "bin", "pip")
                
            subprocess.run([pip_path, "install", "-r", "requirements.txt"], cwd=project_dir, check=True)
            
            # Create Dockerfile for Flask
            with open(os.path.join(project_dir, "Dockerfile"), "w") as f:
                f.write("""
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
                """)
                
        else:
            logger.info("Using generic Nginx container for unknown project type")
            # Generic fallback
            with open(os.path.join(project_dir, "Dockerfile"), "w") as f:
                f.write("""
FROM nginx:alpine
COPY . /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
                """)
        
        # Build Docker image
        image_name = f"localhost:5005/quickdeploy-{deployment_id}:latest"
        
        # Build with docker
        build_cmd = ["docker", "build", "-t", image_name, "."]
        logger.info(f"Running build command: {' '.join(build_cmd)}")
        subprocess.run(build_cmd, cwd=project_dir, check=True)
        
        # Push to local registry
        push_cmd = ["docker", "push", image_name]
        logger.info(f"Running push command: {' '.join(push_cmd)}")
        subprocess.run(push_cmd, check=True)
        
        logger.info(f"Successfully built and pushed image: {image_name}")
        return image_name, port
    except subprocess.CalledProcessError as e:
        logger.error(f"Build error: {e}")
        logger.error(f"Command output: {e.stdout if hasattr(e, 'stdout') else 'None'}")
        logger.error(f"Command error: {e.stderr if hasattr(e, 'stderr') else 'None'}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during build: {e}")
        return None

def deploy_to_kubernetes(image_name, deployment_id, project_type, port):
    """Deploy the application to Kubernetes"""
    app_name = f"app-{deployment_id[:8]}"
    namespace = "default"
    
    try:
        # Try to delete existing resources if they exist
        try:
            # Check if deployment exists before trying to delete
            apps_v1.read_namespaced_deployment(name=app_name, namespace=namespace)
            logger.info(f"Deleting existing deployment: {app_name}")
            apps_v1.delete_namespaced_deployment(name=app_name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:  # Only log if not a "not found" error
                logger.warning(f"Error checking deployment: {e}")
        
        try:
            # Check if service exists
            v1.read_namespaced_service(name=app_name, namespace=namespace)
            logger.info(f"Deleting existing service: {app_name}")
            v1.delete_namespaced_service(name=app_name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:
                logger.warning(f"Error checking service: {e}")
        
        try:
            # Check if ingress exists
            networking_v1.read_namespaced_ingress(name=app_name, namespace=namespace)
            logger.info(f"Deleting existing ingress: {app_name}")
            networking_v1.delete_namespaced_ingress(name=app_name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:
                logger.warning(f"Error checking ingress: {e}")
        
        # Create deployment
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(name=app_name),
            spec=client.V1DeploymentSpec(
                replicas=1,
                selector=client.V1LabelSelector(
                    match_labels={"app": app_name}
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={"app": app_name}
                    ),
                    spec=client.V1PodSpec(
                        containers=[
                            client.V1Container(
                                name=app_name,
                                image=image_name,
                                ports=[client.V1ContainerPort(container_port=port)]
                            )
                        ]
                    )
                )
            )
        )
        
        logger.info(f"Creating deployment: {app_name}")
        apps_v1.create_namespaced_deployment(namespace=namespace, body=deployment)
        
        # Create service
        service = client.V1Service(
            metadata=client.V1ObjectMeta(name=app_name),
            spec=client.V1ServiceSpec(
                selector={"app": app_name},
                ports=[client.V1ServicePort(port=80, target_port=port)]
            )
        )
        
        logger.info(f"Creating service: {app_name}")
        v1.create_namespaced_service(namespace=namespace, body=service)
        
        # Create ingress
        # Note: Docker Desktop Kubernetes uses a different structure for ingress
        ingress = client.V1Ingress(
            metadata=client.V1ObjectMeta(
                name=app_name,
                annotations={
                    "kubernetes.io/ingress.class": "nginx",
                    "nginx.ingress.kubernetes.io/ssl-redirect": "false"
                }
            ),
            spec=client.V1IngressSpec(
                rules=[
                    client.V1IngressRule(
                        host=f"{app_name}.quickdeploy.local",
                        http=client.V1HTTPIngressRuleValue(
                            paths=[
                                client.V1HTTPIngressPath(
                                    path="/",
                                    path_type="Prefix",
                                    backend=client.V1IngressBackend(
                                        service=client.V1IngressServiceBackend(
                                            name=app_name,
                                            port=client.V1ServiceBackendPort(
                                                number=80
                                            )
                                        )
                                    )
                                )
                            ]
                        )
                    )
                ]
            )
        )
        
        logger.info(f"Creating ingress: {app_name}")
        networking_v1.create_namespaced_ingress(namespace=namespace, body=ingress)
        
        # Add to /etc/hosts if it doesn't already exist
        host_name = f"{app_name}.quickdeploy.local"
        add_to_hosts = True
        
        try:
            with open('/etc/hosts', 'r') as hosts_file:
                if host_name in hosts_file.read():
                    add_to_hosts = False
        except Exception as e:
            logger.warning(f"Could not read /etc/hosts: {e}")
        
        if add_to_hosts:
            try:
                # Need to use sudo to write to /etc/hosts
                command = f"echo '127.0.0.1 {host_name}' | sudo tee -a /etc/hosts > /dev/null"
                logger.info(f"Adding {host_name} to /etc/hosts")
                subprocess.run(command, shell=True, check=True)
            except subprocess.CalledProcessError as e:
                logger.warning(f"Could not add {host_name} to /etc/hosts: {e}")
                logger.warning("You may need to manually add it or run as administrator")
        
        logger.info(f"Deployment successful: http://{app_name}.quickdeploy.local")
        return f"http://{app_name}.quickdeploy.local"
    except Exception as e:
        logger.error(f"Kubernetes deployment error: {e}")
        return None

def process_build_job():
    """Process a build job from the queue"""
    # Get job from queue
    job_data = redis_client.rpop("build_queue")
    if not job_data:
        return False
    
    try:
        job = json.loads(job_data)
        deployment_id = job["id"]
        repo_url = job["repository"]
        branch = job["branch"]
        
        logger.info(f"Processing deployment {deployment_id} for {repo_url} ({branch})")
        
        # Update status to building
        update_deployment_status(deployment_id, "building")
        
        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        try:
            # Clone repository
            logger.info(f"Cloning repository {repo_url} ({branch})...")
            if not clone_repository(repo_url, branch, temp_dir):
                logger.error("Clone failed!")
                update_deployment_status(deployment_id, "failed")
                return True
            
            # Detect project type
            project_type, project_dir = detect_project_type(temp_dir)
            logger.info(f"Detected project type: {project_type}")
            
            # Build project
            logger.info(f"Building project...")
            image_name, port = build_project(project_type, project_dir, temp_dir, deployment_id)
            if not image_name:
                logger.error("Build failed!")
                update_deployment_status(deployment_id, "failed")
                return True
            
            # Deploy to Kubernetes
            logger.info(f"Deploying to Kubernetes...")
            deployment_url = deploy_to_kubernetes(image_name, deployment_id, project_type, port)
            if not deployment_url:
                logger.error("Deployment failed!")
                update_deployment_status(deployment_id, "failed")
                return True
            
            # Update status to deployed
            update_deployment_status(deployment_id, "deployed", deployment_url)
            logger.info(f"Deployment successful: {deployment_url}")
            
        finally:
            # Clean up temporary directory
            logger.info(f"Cleaning up temporary directory...")
            shutil.rmtree(temp_dir)
    except Exception as e:
        logger.error(f"Error processing job: {e}")
        if 'deployment_id' in locals():
            update_deployment_status(deployment_id, "failed")
    
    return True

# Main worker loop
def main():
    logger.info("QuickDeploy build worker started")
    
    try:
        # Initialize SQLite database
        conn = sqlite3.connect('quickdeploy.db')
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS deployments (
            id TEXT PRIMARY KEY,
            repository TEXT,
            branch TEXT,
            commit_hash TEXT,
            status TEXT,
            created_at TEXT,
            updated_at TEXT,
            url TEXT
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT,
            repository_url TEXT,
            created_at TEXT
        )
        ''')
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
    
    while True:
        try:
            if not process_build_job():
                # No jobs in queue, sleep for a bit
                time.sleep(5)
        except Exception as e:
            logger.error(f"Error processing job: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()