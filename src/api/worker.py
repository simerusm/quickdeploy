# worker.py - Build service worker for macOS with Docker Desktop Kubernetes
import redis
import json
import os
import tempfile
import subprocess
import time
import sqlite3
import shutil
from kubernetes import client, config
from datetime import datetime
import socket

# Connect to Redis
redis_client = redis.Redis(host='localhost', port=6379, db=0)

# Load kubernetes config with fallback options
try:
    # Try loading from default kubeconfig file
    config.load_kube_config()
    print("Loaded Kubernetes config from kubeconfig file")
except Exception as e:
    print(f"Error loading kubeconfig: {e}")
    print("Attempting to load in-cluster config")
    try:
        # Try in-cluster config as fallback
        config.load_incluster_config()
        print("Loaded in-cluster Kubernetes config")
    except Exception as e:
        print(f"Error loading in-cluster config: {e}")
        print("WARNING: Kubernetes configuration failed!")

# Initialize Kubernetes API clients
v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()
networking_v1 = client.NetworkingV1Api()

def update_deployment_status(deployment_id, status, url=""):
    """Update deployment status in database"""
    conn = sqlite3.connect('quickdeploy.db')
    cursor = conn.cursor()
    updated_at = datetime.now().isoformat()
    cursor.execute(
        "UPDATE deployments SET status = ?, updated_at = ?, url = ? WHERE id = ?",
        (status, updated_at, url, deployment_id)
    )
    conn.commit()
    conn.close()

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
                return True
            else:
                print(f"Local directory {local_path} does not exist")
                return False
        else:
            # Normal git clone
            subprocess.run(
                ["git", "clone", "--branch", branch, repo_url, temp_dir],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            return True
    except subprocess.CalledProcessError as e:
        print(f"Git clone error: {e}")
        print(f"Error output: {e.stderr.decode() if e.stderr else 'None'}")
        return False
    except Exception as e:
        print(f"Clone error: {e}")
        return False

def detect_project_type(temp_dir):
    """Detect project type based on files"""
    # Check for package.json (Node.js)
    if os.path.exists(os.path.join(temp_dir, "package.json")):
        with open(os.path.join(temp_dir, "package.json")) as f:
            package_json = json.load(f)
        
        # Check for Next.js
        if "dependencies" in package_json and "next" in package_json["dependencies"]:
            return "nextjs"
        # Check for React
        elif "dependencies" in package_json and "react" in package_json["dependencies"]:
            return "react"
        else:
            return "nodejs"
            
    # Check for requirements.txt (Python)
    elif os.path.exists(os.path.join(temp_dir, "requirements.txt")):
        # Check for Django
        if os.path.exists(os.path.join(temp_dir, "manage.py")):
            return "django"
        # Check for Flask
        else:
            with open(os.path.join(temp_dir, "requirements.txt")) as f:
                if "flask" in f.read().lower():
                    return "flask"
                else:
                    return "python"
    else:
        return "unknown"

def build_project(project_type, temp_dir, deployment_id):
    """Build project based on type"""
    try:
        if project_type == "nextjs":
            subprocess.run(["npm", "install"], cwd=temp_dir, check=True)
            subprocess.run(["npm", "run", "build"], cwd=temp_dir, check=True)
            
            # Create Dockerfile for Next.js
            with open(os.path.join(temp_dir, "Dockerfile"), "w") as f:
                f.write("""
FROM node:16-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install --production
COPY .next ./.next
COPY public ./public
COPY node_modules ./node_modules
CMD ["npm", "start"]
                """)
                
        elif project_type == "react":
            subprocess.run(["npm", "install"], cwd=temp_dir, check=True)
            subprocess.run(["npm", "run", "build"], cwd=temp_dir, check=True)
            
            # Create Dockerfile for React
            with open(os.path.join(temp_dir, "Dockerfile"), "w") as f:
                f.write("""
FROM nginx:alpine
COPY build /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
                """)
                
        elif project_type == "flask":
            # Create virtual environment
            subprocess.run(["python3", "-m", "venv", "venv"], cwd=temp_dir, check=True)
            
            # Install requirements
            if os.name == 'nt':  # Windows
                pip_path = os.path.join(temp_dir, "venv", "Scripts", "pip")
            else:  # Unix-like
                pip_path = os.path.join(temp_dir, "venv", "bin", "pip")
                
            subprocess.run([pip_path, "install", "-r", "requirements.txt"], cwd=temp_dir, check=True)
            
            # Create Dockerfile for Flask
            with open(os.path.join(temp_dir, "Dockerfile"), "w") as f:
                f.write("""
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
                """)
                
        else:
            # Generic fallback
            with open(os.path.join(temp_dir, "Dockerfile"), "w") as f:
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
        print(f"Running build command: {' '.join(build_cmd)}")
        subprocess.run(build_cmd, cwd=temp_dir, check=True)
        
        # Push to local registry
        push_cmd = ["docker", "push", image_name]
        print(f"Running push command: {' '.join(push_cmd)}")
        subprocess.run(push_cmd, check=True)
        
        return image_name
    except subprocess.CalledProcessError as e:
        print(f"Build error: {e}")
        print(f"Command output: {e.stdout if hasattr(e, 'stdout') else 'None'}")
        print(f"Command error: {e.stderr if hasattr(e, 'stderr') else 'None'}")
        return None
    except Exception as e:
        print(f"Unexpected error during build: {e}")
        return None

def deploy_to_kubernetes(image_name, deployment_id, project_type):
    """Deploy the application to Kubernetes"""
    app_name = f"app-{deployment_id[:8]}"
    namespace = "default"
    
    try:
        # Try to delete existing resources if they exist
        try:
            # Check if deployment exists before trying to delete
            apps_v1.read_namespaced_deployment(name=app_name, namespace=namespace)
            print(f"Deleting existing deployment: {app_name}")
            apps_v1.delete_namespaced_deployment(name=app_name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:  # Only print if not a "not found" error
                print(f"Error checking deployment: {e}")
        
        try:
            # Check if service exists
            v1.read_namespaced_service(name=app_name, namespace=namespace)
            print(f"Deleting existing service: {app_name}")
            v1.delete_namespaced_service(name=app_name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:
                print(f"Error checking service: {e}")
        
        try:
            # Check if ingress exists
            networking_v1.read_namespaced_ingress(name=app_name, namespace=namespace)
            print(f"Deleting existing ingress: {app_name}")
            networking_v1.delete_namespaced_ingress(name=app_name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:
                print(f"Error checking ingress: {e}")
        
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
                                ports=[client.V1ContainerPort(container_port=80)]
                            )
                        ]
                    )
                )
            )
        )
        
        print(f"Creating deployment: {app_name}")
        apps_v1.create_namespaced_deployment(namespace=namespace, body=deployment)
        
        # Create service
        service = client.V1Service(
            metadata=client.V1ObjectMeta(name=app_name),
            spec=client.V1ServiceSpec(
                selector={"app": app_name},
                ports=[client.V1ServicePort(port=80, target_port=80)]
            )
        )
        
        print(f"Creating service: {app_name}")
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
        
        print(f"Creating ingress: {app_name}")
        networking_v1.create_namespaced_ingress(namespace=namespace, body=ingress)
        
        # Add to /etc/hosts if it doesn't already exist
        host_name = f"{app_name}.quickdeploy.local"
        add_to_hosts = True
        
        try:
            with open('/etc/hosts', 'r') as hosts_file:
                if host_name in hosts_file.read():
                    add_to_hosts = False
        except:
            print("Could not read /etc/hosts")
        
        if add_to_hosts:
            try:
                # Need to use sudo to write to /etc/hosts
                command = f"echo '127.0.0.1 {host_name}' | sudo tee -a /etc/hosts > /dev/null"
                print(f"Adding {host_name} to /etc/hosts")
                subprocess.run(command, shell=True, check=True)
            except subprocess.CalledProcessError as e:
                print(f"Warning: Could not add {host_name} to /etc/hosts: {e}")
                print("You may need to manually add it or run as administrator")
        
        return f"http://{app_name}.quickdeploy.local"
    except Exception as e:
        print(f"Kubernetes deployment error: {e}")
        return None

def process_build_job():
    """Process a build job from the queue"""
    # Get job from queue
    job_data = redis_client.rpop("build_queue")
    if not job_data:
        return False
    
    job = json.loads(job_data)
    deployment_id = job["id"]
    repo_url = job["repository"]
    branch = job["branch"]
    
    print(f"Processing deployment {deployment_id} for {repo_url} ({branch})")
    
    # Update status to building
    update_deployment_status(deployment_id, "building")
    
    # Create temporary directory
    temp_dir = tempfile.mkdtemp()
    try:
        # Clone repository
        print(f"Cloning repository {repo_url} ({branch})...")
        if not clone_repository(repo_url, branch, temp_dir):
            print("Clone failed!")
            update_deployment_status(deployment_id, "failed")
            return True
        
        # Detect project type
        project_type = detect_project_type(temp_dir)
        print(f"Detected project type: {project_type}")
        
        # Build project
        print(f"Building project...")
        image_name = build_project(project_type, temp_dir, deployment_id)
        if not image_name:
            print("Build failed!")
            update_deployment_status(deployment_id, "failed")
            return True
        
        # Deploy to Kubernetes
        print(f"Deploying to Kubernetes...")
        deployment_url = deploy_to_kubernetes(image_name, deployment_id, project_type)
        if not deployment_url:
            print("Deployment failed!")
            update_deployment_status(deployment_id, "failed")
            return True
        
        # Update status to deployed
        update_deployment_status(deployment_id, "deployed", deployment_url)
        print(f"Deployment successful: {deployment_url}")
        
    finally:
        # Clean up temporary directory
        print(f"Cleaning up temporary directory...")
        shutil.rmtree(temp_dir)
    
    return True

# Main worker loop
def main():
    print("QuickDeploy build worker started")
    
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
    
    while True:
        try:
            if not process_build_job():
                # No jobs in queue, sleep for a bit
                time.sleep(5)
        except Exception as e:
            print(f"Error processing job: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()