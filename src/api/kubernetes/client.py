from kubernetes import client, config
import logging

logger = logging.getLogger('quickdeploy')

# Initialize global variables
v1 = None
apps_v1 = None
networking_v1 = None

def initialize_kubernetes():
    """Initialize Kubernetes client with fallback options"""
    global v1, apps_v1, networking_v1
    
    try:
        # Try loading from default kubeconfig file
        config.load_kube_config()
        logger.info("Loaded Kubernetes config from kubeconfig file")
        
        # Initialize API clients
        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        networking_v1 = client.NetworkingV1Api()
        
        # Test the connection
        apps_v1.list_namespaced_deployment(namespace="default")
        logger.info("Successfully connected to Kubernetes API")
        return True
    except Exception as e:
        logger.error(f"Error loading kubeconfig: {e}")
        logger.info("Attempting to load in-cluster config")
        try:
            # Try in-cluster config as fallback
            config.load_incluster_config()
            
            # Initialize API clients
            v1 = client.CoreV1Api()
            apps_v1 = client.AppsV1Api()
            networking_v1 = client.NetworkingV1Api()
            
            # Test the connection
            apps_v1.list_namespaced_deployment(namespace="default")
            logger.info("Successfully connected to Kubernetes API using in-cluster config")
            return True
        except Exception as e:
            logger.error(f"Error loading in-cluster config: {e}")
            logger.warning("Kubernetes configuration failed!")
            return False