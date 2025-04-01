import os
import json
import logging
import yaml

logger = logging.getLogger('quickdeploy')

def detect_database_needs(project_dir):
    """Detect database requirements from code"""
    database_needs = []
    
    # Check for quickdeploy.yaml
    config_path = os.path.join(project_dir, "quickdeploy.yaml")
    if os.path.exists(config_path):
        try:
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