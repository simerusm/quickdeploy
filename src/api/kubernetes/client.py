from kubernetes import client, config
import logging

logger = logging.getLogger('quickdeploy')

class KubernetesClient:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = KubernetesClient()
        return cls._instance
    
    def __init__(self):
        self.v1 = None
        self.apps_v1 = None
        self.networking_v1 = None
        self.initialized = False
    
    def initialize(self):
        """Initialize Kubernetes client with fallback options"""
        if self.initialized:
            return True
            
        try:
            # Try loading from default kubeconfig file
            config.load_kube_config()
            logger.info("Loaded Kubernetes config from kubeconfig file")
            
            # Initialize API clients
            self.v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            self.networking_v1 = client.NetworkingV1Api()
            
            # Test connection
            self.apps_v1.list_namespaced_deployment(namespace="default")
            logger.info("Successfully connected to Kubernetes API")
            self.initialized = True
            return True
        except Exception as e:
            logger.error(f"Error initializing Kubernetes client: {e}")
            try:
                # Try in-cluster config as fallback
                config.load_incluster_config()
                
                # Initialize API clients
                self.v1 = client.CoreV1Api()
                self.apps_v1 = client.AppsV1Api()
                self.networking_v1 = client.NetworkingV1Api()
                
                # Test connection
                self.apps_v1.list_namespaced_deployment(namespace="default")
                logger.info("Successfully connected to Kubernetes API using in-cluster config")
                self.initialized = True
                return True
            except Exception as e:
                logger.error(f"Error initializing Kubernetes client with in-cluster config: {e}")
                return False
    
    def is_initialized(self):
        return self.initialized

# Initialize the singleton instance
k8s_client = KubernetesClient.get_instance()