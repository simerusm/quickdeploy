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
import random
import string

INGRESS_PORT = 8090

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
    
def detect_database_needs(project_dir):
    """Detect database requirements from code"""
    database_needs = []
    
    # Check for quickdeploy.yaml
    config_path = os.path.join(project_dir, "quickdeploy.yaml")
    if os.path.exists(config_path):
        try:
            import yaml
            with open(config_path) as f:
                config = yaml.safe_load(f)
                if config and "databases" in config:
                    for name, db_config in config["databases"].items():
                        database_needs.append(db_config)
                    return database_needs
        except Exception as e:
            logger.warning(f"Error reading quickdeploy.yaml: {e}")
    
    # Check package.json for Node.js projects
    package_json_path = os.path.join(project_dir, "package.json")
    if os.path.exists(package_json_path):
        try:
            with open(package_json_path) as f:
                data = json.load(f)
                deps = {}
                if "dependencies" in data:
                    deps.update(data["dependencies"])
                if "devDependencies" in data:
                    deps.update(data["devDependencies"])
                
                if any(pkg in deps for pkg in ["pg", "postgres", "typeorm", "sequelize"]):
                    database_needs.append({"type": "postgres", "version": "14"})
        except Exception as e:
            logger.warning(f"Error parsing package.json: {e}")
    
    # Check requirements.txt for Python projects
    req_path = os.path.join(project_dir, "requirements.txt")
    if os.path.exists(req_path):
        try:
            with open(req_path) as f:
                content = f.read().lower()
                if "psycopg2" in content or "sqlalchemy" in content or "flask-sqlalchemy" in content:
                    database_needs.append({"type": "postgres", "version": "14"})
        except Exception as e:
            logger.warning(f"Error parsing requirements.txt: {e}")
    
    return database_needs

def provision_database(db_type, db_version, app_name):
    """Create a database container for the application"""
    try:
        if db_type == "postgres":
            # Generate random password
            import random
            import string
            password = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16))
            
            # Create PostgreSQL container
            container_name = f"{app_name}-postgres"
            logger.info(f"Creating PostgreSQL container: {container_name}")
            
            subprocess.run([
                "docker", "run", "-d",
                "--name", container_name,
                "-e", f"POSTGRES_PASSWORD={password}",
                "-e", f"POSTGRES_USER=quickdeploy",
                "-e", f"POSTGRES_DB=app",
                f"postgres:{db_version}-alpine"
            ], check=True)
            
            # Get container IP
            container_ip = subprocess.run(
                ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container_name],
                capture_output=True, text=True, check=True
            ).stdout.strip()
            
            logger.info(f"PostgreSQL container IP: {container_ip}")
            
            return {
                "type": "postgres",
                "host": container_ip,
                "port": 5432,
                "database": "app",
                "username": "quickdeploy",
                "password": password,
                "url": f"postgresql://quickdeploy:{password}@{container_ip}:5432/app"
            }
        else:
            logger.warning(f"Unsupported database type: {db_type}")
            return None
    except Exception as e:
        logger.error(f"Error provisioning database: {e}")
        return None
    
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

def scan_repository(temp_dir):
    """
    Scan a repository for deployable services using a three-step approach:
    1. Look for quickdeploy.yaml
    2. Auto-detect services
    3. Transform code if needed
    """
    services = []
    
    # Step 1: Check for quickdeploy.yaml configuration
    config_services = scan_repository_from_config(temp_dir)
    if config_services:
        logger.info(f"Found {len(config_services)} services in quickdeploy.yaml")
        return config_services
    
    # Step 2: Auto-detect services
    services = scan_repository_auto(temp_dir)
    if services:
        logger.info(f"Auto-detected {len(services)} services in repository")
        return services
    
    # Step 3: Fallback to treating repo as a single service
    project_type, project_dir = detect_project_type(temp_dir)
    if project_type != "unknown":
        services.append({
            "name": "main",
            "path": project_dir,
            "type": project_type, 
            "port": detect_default_port(project_type),
            "env": []
        })
        logger.info(f"Treating repository as a single {project_type} service")
    
    return services

def scan_repository_from_config(temp_dir):
    """Scan repository based on quickdeploy.yaml config"""
    services = []
    config_path = os.path.join(temp_dir, "quickdeploy.yaml")
    
    if not os.path.exists(config_path):
        return []
        
    try:
        import yaml
        with open(config_path) as f:
            config = yaml.safe_load(f)
            
        if not config or "services" not in config:
            return []
            
        for service_name, service_config in config["services"].items():
            service_path = service_config.get("path", ".")
            absolute_path = os.path.join(temp_dir, service_path)
            
            services.append({
                "name": service_name,
                "path": absolute_path,
                "type": service_config.get("type", "auto"),
                "port": service_config.get("port", 0),  # 0 means auto-detect
                "env": service_config.get("env", []),
                "connections": service_config.get("connections", [])
            })
            
        # If database configuration exists, attach to appropriate services
        if "databases" in config:
            for db_name, db_config in config["databases"].items():
                db_info = {
                    "type": db_config.get("type", "postgres"),
                    "version": db_config.get("version", "14"),
                    "name": db_name
                }
                
                # Attach to specific services if specified
                if "services" in db_config:
                    for service_name in db_config["services"]:
                        for service in services:
                            if service["name"] == service_name:
                                if "databases" not in service:
                                    service["databases"] = []
                                service["databases"].append(db_info)
                # Otherwise attach to all services
                else:
                    for service in services:
                        if "databases" not in service:
                            service["databases"] = []
                        service["databases"].append(db_info)
                        
    except Exception as e:
        logger.error(f"Error parsing quickdeploy.yaml: {e}")
        return []
        
    return services

def scan_repository_auto(temp_dir):
    """Auto-detect services in a repository without requiring config"""
    services = []
    
    # Recursively search for deployable services in subdirectories
    for item in os.listdir(temp_dir):
        item_path = os.path.join(temp_dir, item)
        
        # Skip hidden directories and common non-service directories
        if item.startswith('.') or item in ['node_modules', '__pycache__', 'venv', 'env', 'dist', 'build']:
            continue
            
        if os.path.isdir(item_path):
            # Check if this directory contains a deployable service
            project_type, project_dir = detect_project_type(item_path)
            
            if project_type != "unknown":
                # This is a deployable service
                service = {
                    "name": item.lower(),  # Use directory name as service name
                    "path": project_dir,
                    "type": project_type,
                    "port": detect_default_port(project_type),
                    "env": [],
                    "connects_to": [],  # Will be filled in later,
                    "service_role": "unknown"  # Default role
                }
                
                # For frontend services, auto-connect to backend services
                if project_type in ["nextjs", "react", "vue"]:
                    service["service_role"] = "frontend"
                elif project_type in ["flask", "django", "express", "nodejs"]:
                    service["service_role"] = "backend"
                
                services.append(service)
    
    # Establish connections between services
    if len(services) > 1:
        frontends = [s for s in services if s.get("service_role") == "frontend"]
        backends = [s for s in services if s.get("service_role") == "backend"]
        
        # Connect frontends to backends
        for frontend in frontends:
            for backend in backends:
                frontend["connects_to"].append(backend["name"])
                
                # Add environment variables for API URL with full domain and port
                if frontend["type"] == "nextjs":
                    frontend["env"].append(f"NEXT_PUBLIC_API_URL=http://{backend['name']}.quickdeploy.local:{INGRESS_PORT}")
                elif frontend["type"] == "react":
                    frontend["env"].append(f"REACT_APP_API_URL=http://{backend['name']}.quickdeploy.local:{INGRESS_PORT}")
                else:
                    frontend["env"].append(f"VUE_APP_API_URL=http://{backend['name']}.quickdeploy.local:{INGRESS_PORT}")
                    
                # Add CORS environment variables to backend - include all possible frontend URLs
                if backend["type"] in ["flask", "django", "nodejs"]:
                    backend["env"].append(f"CORS_ORIGIN=http://{frontend['name']}.quickdeploy.local:{INGRESS_PORT}")
    
    return services

def detect_project_type(directory):
    """
    Detect the type of project in a directory
    Returns: (project_type, project_directory)
    """
    if not os.path.isdir(directory):
        return "unknown", directory
        
    # Check for package.json (Node.js)
    package_json_path = os.path.join(directory, "package.json")
    if os.path.exists(package_json_path):
        try:
            with open(package_json_path) as f:
                package_json = json.load(f)
            
            # Check for Next.js
            if "dependencies" in package_json and "next" in package_json["dependencies"]:
                return "nextjs", directory
            # Check for React
            elif "dependencies" in package_json and "react" in package_json["dependencies"]:
                if "react-dom" in package_json["dependencies"]:
                    return "react", directory
            # Check for Vue.js
            elif "dependencies" in package_json and "vue" in package_json["dependencies"]:
                return "vue", directory
            # Check for Express
            elif "dependencies" in package_json and "express" in package_json["dependencies"]:
                return "nodejs", directory
            else:
                return "nodejs", directory
        except Exception as e:
            logger.warning(f"Error parsing package.json: {e}")
            
    # Check for requirements.txt (Python)
    requirements_path = os.path.join(directory, "requirements.txt")
    if os.path.exists(requirements_path):
        try:
            with open(requirements_path) as f:
                requirements = f.read().lower()
                
            # Check for Flask
            if "flask" in requirements:
                return "flask", directory
            # Check for Django
            elif "django" in requirements:
                return "django", directory
            else:
                return "python", directory
        except Exception as e:
            logger.warning(f"Error reading requirements.txt: {e}")
    
    # If no recognized project type, recurse into subdirectories
    # to find potential nested projects (common in monorepos)
    for item in os.listdir(directory):
        item_path = os.path.join(directory, item)
        if os.path.isdir(item_path) and not item.startswith('.') and item not in ['node_modules', '__pycache__', 'venv']:
            project_type, project_dir = detect_project_type(item_path)
            if project_type != "unknown":
                return project_type, project_dir
    
    return "unknown", directory

def detect_default_port(project_type):
    """Return the default port for a project type"""
    if project_type == "nextjs":
        return 3000
    elif project_type == "react":
        return 3000
    elif project_type == "vue":
        return 8080
    elif project_type == "flask":
        return 5000
    elif project_type == "django":
        return 8000
    elif project_type == "nodejs":
        return 3000
    else:
        return 80

def transform_service_code(service, service_map):
    """
    Transform code in a service to replace hardcoded URLs with service references
    - service: The service being transformed
    - service_map: Dictionary mapping service names to their deployment IDs
    """
    path = service["path"]
    service_role = service.get("service_role", "")
    
    if service_role == "frontend":
        # Find and transform hardcoded API URLs in frontend code
        transform_frontend_urls(path, service_map)
    elif service_role == "backend":
        # Update CORS and other configurations in backend code
        transform_backend_config(path, service_map)

def transform_frontend_urls(directory, service_map):
    """Replace hardcoded API URLs in frontend code"""
    backend_services = {name: info for name, info in service_map.items() 
                       if info.get("service_role") == "backend"}
    
    if not backend_services:
        return
        
    # First backend service URL to use if we find hardcoded URLs
    default_backend = list(backend_services.values())[0]
    default_backend_url = f"http://app-{default_backend['deployment_id']}"
    
    # Scan for common patterns in JavaScript files
    for root, dirs, files in os.walk(directory):
        # Skip node_modules and other build directories
        if 'node_modules' in root or 'build' in root or 'dist' in root:
            continue
            
        for file in files:
            # Only process JavaScript/TypeScript files
            if file.endswith(('.js', '.jsx', '.ts', '.tsx')):
                file_path = os.path.join(root, file)
                
                try:
                    with open(file_path, 'r') as f:
                        content = f.read()
                    
                    # Look for localhost or 127.0.0.1 URLs
                    new_content = re.sub(
                        r'(const|let|var)\s+(\w+URL|API_URL|apiUrl|baseUrl|BASE_URL)\s*=\s*[\'"]http://(localhost|127\.0\.0\.1):\d+(/\S*)[\'"]',
                        f'\\1 \\2 = "{default_backend_url}\\4"',
                        content
                    )
                    
                    # Replace fetch or axios calls directly to localhost
                    new_content = re.sub(
                        r'(fetch|axios\.get|axios\.post|axios\.put|axios\.delete)\s*\(\s*[\'"]http://(localhost|127\.0\.0\.1):\d+(/\S*)[\'"]',
                        f'\\1("{default_backend_url}\\3"',
                        new_content
                    )
                    
                    if content != new_content:
                        with open(file_path, 'w') as f:
                            f.write(new_content)
                        logger.info(f"Transformed API URL in {file_path}")
                
                except Exception as e:
                    logger.warning(f"Error transforming {file_path}: {e}")

def transform_backend_config(directory, service_map):
    """Update backend configurations for CORS and database connections"""
    frontend_services = {name: info for name, info in service_map.items() 
                         if info.get("service_role") == "frontend"}
    
    if not frontend_services:
        return
        
    # Generate allowed origins list for CORS
    allowed_origins = [f"http://app-{info['deployment_id']}" for info in frontend_services.values()]
    allowed_origins_str = ", ".join([f'"{origin}"' for origin in allowed_origins])
    
    # Flask specific configuration
    flask_files = find_files(directory, ["app.py", "main.py", "__init__.py"])
    for file_path in flask_files:
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Update CORS configuration
            if "flask_cors" in content.lower() or "flask-cors" in content.lower():
                # Update existing CORS
                new_content = re.sub(
                    r'CORS\s*\(\s*app\s*,\s*resources\s*=\s*\{.*?\}\s*\)',
                    f'CORS(app, resources={{r"/*": {{\"origins\": [{allowed_origins_str}]}}}})',
                    content
                )
                
                if content == new_content:
                    # Try another pattern
                    new_content = re.sub(
                        r'CORS\s*\(\s*app\s*\)',
                        f'CORS(app, resources={{r"/*": {{\"origins\": [{allowed_origins_str}]}}}})',
                        content
                    )
            else:
                # Add CORS if not present
                import_pattern = r'from flask import .*?\n'
                import_replacement = '\\g<0>from flask_cors import CORS\n'
                new_content = re.sub(import_pattern, import_replacement, content)
                
                app_pattern = r'app\s*=\s*Flask\s*\(__name__\)'
                app_replacement = '\\g<0>\nCORS(app, resources={r"/*": {"origins": [' + allowed_origins_str + ']}})'
                new_content = re.sub(app_pattern, app_replacement, new_content)
            
            if content != new_content:
                with open(file_path, 'w') as f:
                    f.write(new_content)
                logger.info(f"Updated CORS configuration in {file_path}")
                
        except Exception as e:
            logger.warning(f"Error transforming {file_path}: {e}")

def find_files(directory, filename_patterns):
    """Find files matching any of the patterns in the directory"""
    matching_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if any(pattern in file for pattern in filename_patterns):
                matching_files.append(os.path.join(root, file))
    return matching_files

def detect_port(project_type, project_dir):
    """Detects the port of the project dynamically."""
    port = 80  # Default fallback port
    
    if project_type == "nextjs" or project_type == "react" or project_type == "nodejs":
        port = detect_node_port(project_dir)
    elif project_type == "flask" or project_type == "django" or project_type == "python":
        port = detect_python_port(project_dir)
    
    logger.info(f"Detected application port: {port}")
    
    return port

def build_project(project_type, project_dir, repo_dir, deployment_id, env=None):
    """Build project based on type with environment variables support"""
    try:
        port = detect_port(project_type, project_dir)
        env = env or {}  # Ensure env is a dictionary even if None is passed

        # Common function to write environment variables to a file
        def write_env_file(filepath, variables):
            with open(filepath, "w") as f:
                for key, value in variables.items():
                    f.write(f"{key}={value}\n")
            logger.info(f"Created environment file at {filepath}")

        if project_type == "nextjs":
            # For Next.js, use .env.production
            env_file = os.path.join(project_dir, ".env.production")
            # Filter for Next.js relevant environment variables
            next_env = {k: v for k, v in env.items() if k.startswith("NEXT_") or k.startswith("NEXT_PUBLIC_")}
            write_env_file(env_file, next_env)

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
COPY .env.production ./
COPY .next ./.next
COPY public ./public
COPY node_modules ./node_modules
CMD ["npm", "start"]
                """)
                
        elif project_type == "react":
            # For React, use .env
            env_file = os.path.join(project_dir, ".env")
            # Filter for React relevant environment variables
            react_env = {k: v for k, v in env.items() if k.startswith("REACT_APP_")}
            write_env_file(env_file, react_env)

            logger.info("Building React project...")
            subprocess.run(["npm", "install"], cwd=project_dir, check=True)
            subprocess.run(["npm", "run", "build"], cwd=project_dir, check=True)
            
            # Create Dockerfile for React - Since React is built at build time, no need to include env vars
            with open(os.path.join(project_dir, "Dockerfile"), "w") as f:
                f.write("""
FROM nginx:alpine
COPY build /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
                """)
                
        elif project_type == "vue":
            # For Vue, use .env.production
            env_file = os.path.join(project_dir, ".env.production")
            # Filter for Vue relevant environment variables
            vue_env = {k: v for k, v in env.items() if k.startswith("VUE_APP_")}
            write_env_file(env_file, vue_env)

            logger.info("Building Vue project...")
            subprocess.run(["npm", "install"], cwd=project_dir, check=True)
            subprocess.run(["npm", "run", "build"], cwd=project_dir, check=True)
            
            # Create Dockerfile for Vue
            with open(os.path.join(project_dir, "Dockerfile"), "w") as f:
                f.write("""
FROM nginx:alpine
COPY dist /usr/share/nginx/html
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
            
            # Create a simple Python script to load environment variables at container startup
            with open(os.path.join(project_dir, "start.sh"), "w") as f:
                f.write("""#!/bin/bash
# Start gunicorn with environment variables
gunicorn --bind 0.0.0.0:5000 app:app
""")
                
            # Create Dockerfile for Flask - Environment variables will be passed via Kubernetes
            with open(os.path.join(project_dir, "Dockerfile"), "w") as f:
                f.write("""
FROM python:3.9-slim
WORKDIR /app

# Install system dependencies required for psycopg2
RUN apt-get update && apt-get install -y \\
    gcc \\
    libpq-dev \\
    python3-dev

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Make startup script executable
RUN chmod +x start.sh

# Run with gunicorn
CMD ["./start.sh"]
                """)
                
        elif project_type == "django":
            logger.info("Building Django project...")
            # Create virtual environment
            subprocess.run(["python3", "-m", "venv", "venv"], cwd=project_dir, check=True)
            
            # Install requirements
            if os.name == 'nt':  # Windows
                pip_path = os.path.join(project_dir, "venv", "Scripts", "pip")
            else:  # Unix-like
                pip_path = os.path.join(project_dir, "venv", "bin", "pip")
                
            subprocess.run([pip_path, "install", "-r", "requirements.txt"], cwd=project_dir, check=True)
            
            # Create Dockerfile for Django - Environment variables will be passed via Kubernetes
            with open(os.path.join(project_dir, "Dockerfile"), "w") as f:
                f.write("""
FROM python:3.9-slim
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    gcc \\
    libpq-dev \\
    python3-dev

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run with gunicorn (adjust your Django project and WSGI module name)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "project.wsgi:application"]
                """)
                
        elif project_type == "nodejs" or project_type == "express":
            # For Node.js/Express, use .env
            env_file = os.path.join(project_dir, ".env")
            write_env_file(env_file, env)

            logger.info("Building Node.js project...")
            subprocess.run(["npm", "install"], cwd=project_dir, check=True)
            
            # Create startup script that loads environment variables
            with open(os.path.join(project_dir, "start.sh"), "w") as f:
                f.write("""#!/bin/sh
node app.js
""")
                
            # Create Dockerfile for Node.js
            with open(os.path.join(project_dir, "Dockerfile"), "w") as f:
                f.write("""
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN chmod +x start.sh
CMD ["./start.sh"]
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

def deploy_to_kubernetes(image_name, deployment_id, project_type, port, db_info=None, service_env=None):
    """Deploy the application to Kubernetes"""
    # Use the full deployment_id to ensure uniqueness between services
    app_name = f"app-{deployment_id}"
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
        
        # Add environment variables for database if provided
        env_vars = []
        if db_info:
            logger.info(f"Adding database environment variables for {db_info['type']}")
            if db_info["type"] == "postgres":
                env_vars = [
                    client.V1EnvVar(name="DATABASE_URL", value=db_info["url"]),
                    client.V1EnvVar(name="DB_HOST", value=db_info["host"]),
                    client.V1EnvVar(name="DB_PORT", value=str(db_info["port"])),
                    client.V1EnvVar(name="DB_NAME", value=db_info["database"]),
                    client.V1EnvVar(name="DB_USER", value=db_info["username"]),
                    client.V1EnvVar(name="DB_PASSWORD", value=db_info["password"])
                ]
        
        # Add service environment variables if provided
        if service_env:
            for key, value in service_env.items():
                env_vars.append(client.V1EnvVar(name=key, value=value))
        
        # Create container
        container = client.V1Container(
            name=app_name,
            image=image_name,
            ports=[client.V1ContainerPort(container_port=port)],
            env=env_vars
        )
        
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
                        containers=[container]
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
        
        logger.info(f"Deployment successful: http://{host_name}")
        return f"http://{host_name}"
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
            
            # Scan for services
            services = scan_repository(temp_dir)
            if not services:
                logger.error("No deployable services found in repository")
                update_deployment_status(deployment_id, "failed")
                return True
                
            logger.info(f"Found {len(services)} services: {[s['name'] for s in services]}")
            
            # For each service, make sure type and port are set correctly
            for service in services:
                # If type is 'auto' or not set, detect it
                if service["type"] == "auto" or not service["type"]:
                    project_type, _ = detect_project_type(service["path"])
                    service["type"] = project_type
                
                # If port is 0 or not set, use default for type
                if not service["port"]:
                    service["port"] = detect_default_port(service["type"])
            
            # Provision databases
            db_infos = {}
            for service in services:
                if "databases" in service:
                    for db_config in service["databases"]:
                        db_name = db_config["name"]
                        if db_name not in db_infos:
                            db_infos[db_name] = provision_database(
                                db_config["type"],
                                db_config.get("version", "14"),
                                f"db-{deployment_id[:8]}-{db_name}"
                            )

            # Generate service deployment IDs
            service_deployment_ids = {}
            for service in services:
                service_name = service["name"]
                service_id = f"{deployment_id[:8]}-{service_name}"
                service_deployment_ids[service_name] = service_id
            
            # Pre-calculate environment variables for all services
            service_environments = {}
            for service in services:
                service_name = service["name"]
                service_env = {}
                
                # Add standard environment variables for connecting to other services
                for other_name, other_id in service_deployment_ids.items():
                    if other_name != service_name:
                        # Internal service URL (for container-to-container communication)
                        service_env[f"{other_name.upper()}_URL"] = f"http://app-{other_id}"
                        
                        # For frontend services, also add the external URL with hostname and port
                        if service["type"] in ["nextjs", "react", "vue"] and other_name == "backend":
                            service_env["NEXT_PUBLIC_API_URL"] = f"http://app-{other_id}.quickdeploy.local:{INGRESS_PORT}"
                            service_env["REACT_APP_API_URL"] = f"http://app-{other_id}.quickdeploy.local:{INGRESS_PORT}"
                            service_env["VUE_APP_API_URL"] = f"http://app-{other_id}.quickdeploy.local:{INGRESS_PORT}"
                
                # Add custom environment variables from config
                for env_entry in service.get("env", []):
                    if "=" in env_entry:
                        key, value = env_entry.split("=", 1)
                        # Replace service references with actual service URLs
                        for other_name, other_id in service_deployment_ids.items():
                            value = value.replace(f"http://{other_name}", f"http://app-{other_id}")
                        service_env[key] = value
                
                service_environments[service_name] = service_env
                
                if "NEXT_PUBLIC_API_URL" in service_env:
                    logger.info(f"Environment for {service_name} includes NEXT_PUBLIC_API_URL: {service_env['NEXT_PUBLIC_API_URL']}")
            
            # First pass: build all services
            service_builds = {}
            
            for service in services:
                service_name = service["name"]
                service_id = service_deployment_ids[service_name]
                
                # Build project with pre-calculated environment variables
                logger.info(f"Building service {service_name} ({service['type']})...")
                image_result = build_project(
                    service["type"],
                    service["path"],
                    temp_dir,
                    service_id,
                    service_environments[service_name]
                )
                
                if not image_result:
                    logger.error(f"Failed to build service {service_name}")
                    update_deployment_status(deployment_id, "failed")
                    return True
                    
                # Unpack the tuple
                image_name, port = image_result
                service["port"] = port  # Update the detected port
                service_builds[service_name] = image_name
            
            # Transform code to fix hardcoded references
            service_map = {
                name: {
                    "deployment_id": id, 
                    "service_role": next((s.get("service_role", "unknown") for s in services if s["name"] == name), "unknown")
                } 
                for name, id in service_deployment_ids.items()
            }
            
            for service in services:
                transform_service_code(service, service_map)
            
            # Second pass: deploy all services with proper connectivity
            deployment_urls = {}
            
            for service in services:
                service_name = service["name"]
                service_id = service_deployment_ids[service_name]
                service_env = service_environments[service_name]
                
                # Add database info if this service uses databases
                db_info = None
                if "databases" in service and service["databases"]:
                    db_name = service["databases"][0]["name"]
                    if db_name in db_infos:
                        db_info = db_infos[db_name]
                
                # Deploy to Kubernetes
                logger.info(f"Deploying service {service_name}...")
                image_name = service_builds[service_name]
                
                deployment_url = deploy_to_kubernetes(
                    image_name,
                    service_id,
                    service["type"],
                    service["port"],
                    db_info,
                    service_env
                )
                
                if not deployment_url:
                    logger.error(f"Failed to deploy service {service_name}")
                    update_deployment_status(deployment_id, "failed")
                    return True
                    
                deployment_urls[service_name] = deployment_url
            
            # Update status to deployed with all URLs
            update_deployment_status(
                deployment_id,
                "deployed",
                json.dumps(deployment_urls)
            )
            
            logger.info(f"Deployment successful: {deployment_urls}")
            
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