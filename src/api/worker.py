import json
import tempfile
import shutil
import time
import redis
from datetime import datetime
import sys

# Custom modules
from .utils.logging import setup_logging
from .config import REDIS_HOST, REDIS_PORT, REDIS_DB, INGRESS_PORT
from .db import init_database, update_deployment_status
from .kubernetes.client import initialize_kubernetes
from .kubernetes.deploy import deploy_to_kubernetes, provision_database
from .utils.files import clone_repository
from .services.scan import scan_repository
from .detection.project import detect_project_type, detect_default_port
from .services.build import build_project
from .services.transform import transform_service_code

# Set up logger
logger = setup_logging()

# Connect to Redis
try:
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
    redis_client.ping()
    logger.info("Connected to Redis successfully")
except Exception as e:
    logger.error(f"Redis connection error: {e}")

# Initialize Kubernetes client
k8s_initialized = initialize_kubernetes()
if not k8s_initialized:
    logger.error("Failed to initialize Kubernetes client. Check configuration.")
    sys.exit(1)

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

def main():
    """Main worker loop"""
    logger.info("QuickDeploy build worker started")
    
    # Initialize database
    init_database()
    
    # Main processing loop
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