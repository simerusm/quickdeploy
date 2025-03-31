import os

# Global constants
INGRESS_PORT = 8090

# Redis configuration
REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
REDIS_DB = int(os.environ.get('REDIS_DB', 0))

# Database configuration
DB_PATH = os.environ.get('DB_PATH', 'quickdeploy.db')

# Docker registry
DOCKER_REGISTRY = os.environ.get('DOCKER_REGISTRY', 'localhost:5005')

# Kubernetes configuration
K8S_NAMESPACE = os.environ.get('K8S_NAMESPACE', 'default')

# Project type configurations
FRONTEND_TYPES = ["nextjs", "react", "vue"]
BACKEND_TYPES = ["flask", "django", "express", "nodejs", "python"]

# Default ports by project type
DEFAULT_PORTS = {
    "nextjs": 3000,
    "react": 3000,
    "vue": 8080,
    "flask": 5000,
    "django": 8000,
    "nodejs": 3000,
    "express": 3000,
    "python": 5000,
    "unknown": 80
}

# Non-service directories to skip
SKIP_DIRECTORIES = ['node_modules', '__pycache__', 'venv', 'env', 'dist', 'build']