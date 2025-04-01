import os
import re
import logging
from ..utils.files import find_files

logger = logging.getLogger('quickdeploy')

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
                        r'(const|let|var)\s+(\w+URL|API_URL|apiUrl|baseUrl|BASE_URL|BACKEND_URL|BACKEND|SERVER_URL|SERVER)\s*=\s*[\'"]http://(localhost|127\.0\.0\.1):\d+(/\S*)[\'"]',
                        f'\\1 \\2 = "{default_backend_url}\\4"',
                        content,
                        flags=re.IGNORECASE
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