import os
import json
import logging
from ..config import DEFAULT_PORTS

logger = logging.getLogger('quickdeploy')

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
    return DEFAULT_PORTS.get(project_type, 80)