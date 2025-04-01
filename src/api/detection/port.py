import os
import re
import json
import logging

logger = logging.getLogger('quickdeploy')

def detect_port(project_type, project_dir):
    """Detects the port of the project dynamically."""
    # Default fallbacks
    default_ports = {
        "nextjs": 3000,
        "react": 3000,
        "vue": 8080,
        "flask": 5000,
        "django": 8000,
        "python": 5000,
        "nodejs": 3000,
        "express": 3000,
        "unknown": 80
    }
    
    detected_port = None
    
    if project_type in ["nextjs", "react", "nodejs", "express"]:
        detected_port = detect_node_port(project_dir)
    elif project_type in ["flask", "django", "python"]:
        detected_port = detect_python_port(project_dir)
    
    # If a port was detected, use it; otherwise, use the default for this project type
    port = detected_port if detected_port else default_ports.get(project_type, 80)
    
    logger.info(f"Detected application port: {port}")
    
    return port

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