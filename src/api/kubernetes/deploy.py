import os
import subprocess
import logging
from kubernetes import client
from ..kubernetes.client import k8s_client
from ..config import INGRESS_PORT, K8S_NAMESPACE

logger = logging.getLogger('quickdeploy')

def deploy_to_kubernetes(image_name, deployment_id, project_type, port, db_info=None, service_env=None):
    """Deploy the application to Kubernetes"""
    # Check if Kubernetes is initialized
    if not k8s_client.is_initialized():
        if not k8s_client.initialize():
            logger.error("Kubernetes clients not initialized")
            return None
    
    app_name = f"app-{deployment_id}"
    namespace = K8S_NAMESPACE
    
    try:
        # Try to delete existing resources if they exist
        try:
            # Check if deployment exists before trying to delete
            k8s_client.apps_v1.read_namespaced_deployment(name=app_name, namespace=namespace)
            logger.info(f"Deleting existing deployment: {app_name}")
            k8s_client.apps_v1.delete_namespaced_deployment(name=app_name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:  # Only log if not a "not found" error
                logger.warning(f"Error checking deployment: {e}")
        
        try:
            # Check if service exists
            k8s_client.v1.read_namespaced_service(name=app_name, namespace=namespace)
            logger.info(f"Deleting existing service: {app_name}")
            k8s_client.v1.delete_namespaced_service(name=app_name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:
                logger.warning(f"Error checking service: {e}")
        
        try:
            # Check if ingress exists
            k8s_client.networking_v1.read_namespaced_ingress(name=app_name, namespace=namespace)
            logger.info(f"Deleting existing ingress: {app_name}")
            k8s_client.networking_v1.delete_namespaced_ingress(name=app_name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:
                logger.warning(f"Error checking ingress: {e}")
        
        # Add environment variables for database if provided
        env_vars = []
        if db_info:
            logger.info(f"Adding database environment variables for {db_info['type']}")
            if db_info["type"] == "postgres":
                env_vars = [
                    client.V1EnvVar(name="DATABASE_URL", value=db_info["url"]),
                    client.V1EnvVar(name="DB_HOST", value=db_info["host"]),
                    client.V1EnvVar(name="DB_PORT", value=str(db_info["port"])),
                    client.V1EnvVar(name="DB_NAME", value=db_info["database"]),
                    client.V1EnvVar(name="DB_USER", value=db_info["username"]),
                    client.V1EnvVar(name="DB_PASSWORD", value=db_info["password"])
                ]
        
        # Add service environment variables if provided
        if service_env:
            for key, value in service_env.items():
                env_vars.append(client.V1EnvVar(name=key, value=value))
        
        # Create container
        container = client.V1Container(
            name=app_name,
            image=image_name,
            ports=[client.V1ContainerPort(container_port=port)],
            env=env_vars
        )
        
        # Create deployment
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(name=app_name),
            spec=client.V1DeploymentSpec(
                replicas=1,
                selector=client.V1LabelSelector(
                    match_labels={"app": app_name}
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={"app": app_name}
                    ),
                    spec=client.V1PodSpec(
                        containers=[container]
                    )
                )
            )
        )
        
        logger.info(f"Creating deployment: {app_name}")
        k8s_client.apps_v1.create_namespaced_deployment(namespace=namespace, body=deployment)
        
        # Create service
        service = client.V1Service(
            metadata=client.V1ObjectMeta(name=app_name),
            spec=client.V1ServiceSpec(
                selector={"app": app_name},
                ports=[client.V1ServicePort(port=80, target_port=port)]
            )
        )
        
        logger.info(f"Creating service: {app_name}")
        k8s_client.v1.create_namespaced_service(namespace=namespace, body=service)
        
        # Create ingress
        # Note: Docker Desktop Kubernetes uses a different structure for ingress
        ingress = client.V1Ingress(
            metadata=client.V1ObjectMeta(
                name=app_name,
                annotations={
                    "kubernetes.io/ingress.class": "nginx",
                    "nginx.ingress.kubernetes.io/ssl-redirect": "false"
                }
            ),
            spec=client.V1IngressSpec(
                rules=[
                    client.V1IngressRule(
                        host=f"{app_name}.quickdeploy.local",
                        http=client.V1HTTPIngressRuleValue(
                            paths=[
                                client.V1HTTPIngressPath(
                                    path="/",
                                    path_type="Prefix",
                                    backend=client.V1IngressBackend(
                                        service=client.V1IngressServiceBackend(
                                            name=app_name,
                                            port=client.V1ServiceBackendPort(
                                                number=80
                                            )
                                        )
                                    )
                                )
                            ]
                        )
                    )
                ]
            )
        )
        
        logger.info(f"Creating ingress: {app_name}")
        k8s_client.networking_v1.create_namespaced_ingress(namespace=namespace, body=ingress)
        
        # Add to /etc/hosts if it doesn't already exist
        host_name = f"{app_name}.quickdeploy.local"
        add_to_hosts = True
        
        try:
            with open('/etc/hosts', 'r') as hosts_file:
                if host_name in hosts_file.read():
                    add_to_hosts = False
        except Exception as e:
            logger.warning(f"Could not read /etc/hosts: {e}")
        
        if add_to_hosts:
            try:
                # Need to use sudo to write to /etc/hosts
                command = f"echo '127.0.0.1 {host_name}' | sudo tee -a /etc/hosts > /dev/null"
                logger.info(f"Adding {host_name} to /etc/hosts")
                subprocess.run(command, shell=True, check=True)
            except subprocess.CalledProcessError as e:
                logger.warning(f"Could not add {host_name} to /etc/hosts: {e}")
                logger.warning("You may need to manually add it or run as administrator")
        
        logger.info(f"Deployment successful: http://{host_name}")
        return f"http://{host_name}"
    except Exception as e:
        logger.error(f"Kubernetes deployment error: {e}")
        return None

def provision_database(db_type, db_version, app_name):
    """Create a database container for the application"""
    try:
        if db_type == "postgres":
            # Generate random password
            import random
            import string
            password = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16))
            
            # Create PostgreSQL container
            container_name = f"{app_name}-postgres"
            logger.info(f"Creating PostgreSQL container: {container_name}")
            
            subprocess.run([
                "docker", "run", "-d",
                "--name", container_name,
                "-e", f"POSTGRES_PASSWORD={password}",
                "-e", f"POSTGRES_USER=quickdeploy",
                "-e", f"POSTGRES_DB=app",
                f"postgres:{db_version}-alpine"
            ], check=True)
            
            # Get container IP
            container_ip = subprocess.run(
                ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container_name],
                capture_output=True, text=True, check=True
            ).stdout.strip()
            
            logger.info(f"PostgreSQL container IP: {container_ip}")
            
            return {
                "type": "postgres",
                "host": container_ip,
                "port": 5432,
                "database": "app",
                "username": "quickdeploy",
                "password": password,
                "url": f"postgresql://quickdeploy:{password}@{container_ip}:5432/app"
            }
        else:
            logger.warning(f"Unsupported database type: {db_type}")
            return None
    except Exception as e:
        logger.error(f"Error provisioning database: {e}")
        return None