import os
import subprocess
import logging
from ..detection.port import detect_port
from ..config import DOCKER_REGISTRY
from ..utils.files import write_env_file
import json

logger = logging.getLogger('quickdeploy')

def build_project(project_type, project_dir, repo_dir, deployment_id, env=None):
    """Build project based on type with environment variables support"""
    try:
        port = detect_port(project_type, project_dir)
        env = env or {}  # Ensure env is a dictionary even if None is passed

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
                f.write(f"""
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install --production
COPY .env.production ./
COPY .next ./.next
COPY public ./public
COPY node_modules ./node_modules

# Expose the detected port
EXPOSE {port}

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
                f.write(f"""
FROM nginx:alpine
COPY build /usr/share/nginx/html

# Configure nginx to handle SPA routing
RUN echo 'server {{\\n\\
    listen {port};\\n\\
    root /usr/share/nginx/html;\\n\\
    location / {{\\n\\
        try_files $uri $uri/ /index.html;\\n\\
    }}\\n\\
}}' > /etc/nginx/conf.d/default.conf

EXPOSE {port}
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
                f.write(f"""
FROM nginx:alpine
COPY dist /usr/share/nginx/html

# Configure nginx to handle SPA routing
RUN echo 'server {{\\n\\
    listen {port};\\n\\
    root /usr/share/nginx/html;\\n\\
    location / {{\\n\\
        try_files $uri $uri/ /index.html;\\n\\
    }}\\n\\
}}' > /etc/nginx/conf.d/default.conf

EXPOSE {port}
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
                f.write(f"""#!/bin/bash
# Start gunicorn with environment variables
gunicorn --bind 0.0.0.0:{port} app:app
""")
                
            # Create Dockerfile for Flask - Environment variables will be passed via Kubernetes
            with open(os.path.join(project_dir, "Dockerfile"), "w") as f:
                f.write(f"""
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
RUN pip install gunicorn

# Copy application code
COPY . .

# Make startup script executable
RUN chmod +x start.sh

# Expose the detected port
EXPOSE {port}

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
            
            # Detect Django project name
            django_project = "project"  # Default project name
            for item in os.listdir(project_dir):
                if os.path.isdir(os.path.join(project_dir, item)) and os.path.exists(os.path.join(project_dir, item, 'settings.py')):
                    django_project = item
                    break
            
            # Create start script
            with open(os.path.join(project_dir, "start.sh"), "w") as f:
                f.write(f"""#!/bin/bash
# Apply migrations
python manage.py migrate

# Start gunicorn
gunicorn --bind 0.0.0.0:{port} {django_project}.wsgi:application
""")
            
            # Create Dockerfile for Django - Environment variables will be passed via Kubernetes
            with open(os.path.join(project_dir, "Dockerfile"), "w") as f:
                f.write(f"""
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
RUN pip install gunicorn

# Copy application code
COPY . .

# Make startup script executable
RUN chmod +x start.sh

# Expose the detected port
EXPOSE {port}

# Run with gunicorn
CMD ["./start.sh"]
                """)
                
        elif project_type == "nodejs" or project_type == "express":
            # For Node.js/Express, use .env
            env_file = os.path.join(project_dir, ".env")
            write_env_file(env_file, env)

            logger.info("Building Node.js project...")
            subprocess.run(["npm", "install"], cwd=project_dir, check=True)
            
            # Try to determine the entry point
            entry_point = "app.js"  # Default
            package_json_path = os.path.join(project_dir, "package.json")
            if os.path.exists(package_json_path):
                with open(package_json_path, 'r') as f:
                    package_data = json.load(f)
                    if "main" in package_data:
                        entry_point = package_data["main"]
            
            # Create startup script that loads environment variables
            with open(os.path.join(project_dir, "start.sh"), "w") as f:
                f.write(f"""#!/bin/sh
# Start Node.js application
node {entry_point}
""")
                
            # Create Dockerfile for Node.js
            with open(os.path.join(project_dir, "Dockerfile"), "w") as f:
                f.write(f"""
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN chmod +x start.sh

# Expose the detected port
EXPOSE {port}

CMD ["./start.sh"]
                """)
                
        else:
            logger.info("Using generic Nginx container for unknown project type")
            # Generic fallback
            with open(os.path.join(project_dir, "Dockerfile"), "w") as f:
                f.write(f"""
FROM nginx:alpine
COPY . /usr/share/nginx/html
EXPOSE {port}
CMD ["nginx", "-g", "daemon off;"]
                """)
        
        # Build Docker image
        image_name = f"{DOCKER_REGISTRY}/quickdeploy-{deployment_id}:latest"
        
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