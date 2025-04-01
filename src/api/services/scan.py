import os
import logging
import json
from ..config import INGRESS_PORT, FRONTEND_TYPES, BACKEND_TYPES, SKIP_DIRECTORIES
from ..detection.project import detect_project_type, detect_default_port
import yaml
import re

logger = logging.getLogger('quickdeploy')

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
        
        with open(config_path) as f:
            config = yaml.safe_load(f)
            
        if not config or "services" not in config:
            return []
            
        for service_name, service_config in config["services"].items():
            service_path = service_config.get("path", ".")
            absolute_path = os.path.join(temp_dir, service_path)
            service_type = service_config.get("type", "auto")
            
            # Auto-detect type if set to "auto"
            if service_type == "auto":
                service_type, _ = detect_project_type(absolute_path)
            
            # Set service role based on type
            service_role = "unknown"
            if service_type in FRONTEND_TYPES:
                service_role = "frontend"
            elif service_type in BACKEND_TYPES:
                service_role = "backend"
                
            services.append({
                "name": service_name,
                "path": absolute_path,
                "type": service_type,
                "port": service_config.get("port", detect_default_port(service_type)),
                "env": service_config.get("env", []),
                "connections": service_config.get("connections", []),
                "service_role": service_role
            })
            
        # If we have multiple services, add inter-service connectivity environment variables
        if len(services) > 1:
            # Identify frontend and backend services
            frontends = [s for s in services if s["service_role"] == "frontend"]
            backends = [s for s in services if s["service_role"] == "backend"]
            
            # Connect frontends to backends with proper environment variables
            for frontend in frontends:
                for backend in backends:
                    if "connections" not in frontend or backend["name"] in frontend["connections"]:
                        # Add environment variable for API URL if not already defined
                        if frontend["type"] == "nextjs":
                            env_var = f"NEXT_PUBLIC_API_URL=http://{backend['name']}.quickdeploy.local:{INGRESS_PORT}"
                            if not any(e.startswith("NEXT_PUBLIC_API_URL=") for e in frontend["env"]):
                                frontend["env"].append(env_var)
                        elif frontend["type"] == "react":
                            env_var = f"REACT_APP_API_URL=http://{backend['name']}.quickdeploy.local:{INGRESS_PORT}"
                            if not any(e.startswith("REACT_APP_API_URL=") for e in frontend["env"]):
                                frontend["env"].append(env_var)
                        else:  # Vue
                            env_var = f"VUE_APP_API_URL=http://{backend['name']}.quickdeploy.local:{INGRESS_PORT}"
                            if not any(e.startswith("VUE_APP_API_URL=") for e in frontend["env"]):
                                frontend["env"].append(env_var)
                                
                        # Add CORS environment variable to backend if not already defined
                        if backend["type"] in BACKEND_TYPES:
                            env_var = f"CORS_ORIGIN=http://{frontend['name']}.quickdeploy.local:{INGRESS_PORT}"
                            if not any(e.startswith("CORS_ORIGIN=") for e in backend["env"]):
                                backend["env"].append(env_var)
            
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
        if item.startswith('.') or item in SKIP_DIRECTORIES:
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
                    "connects_to": [],
                    "service_role": "unknown"  # Default role
                }
                
                # For frontend services, auto-connect to backend services
                if project_type in FRONTEND_TYPES:
                    service["service_role"] = "frontend"
                elif project_type in BACKEND_TYPES:
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
                if backend["type"] in BACKEND_TYPES:
                    backend["env"].append(f"CORS_ORIGIN=http://{frontend['name']}.quickdeploy.local:{INGRESS_PORT}")
    
    return services