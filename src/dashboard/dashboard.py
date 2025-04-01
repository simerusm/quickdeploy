from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response
import requests
import json
from datetime import datetime
import threading
import time
import redis
import os
import logging
import sys

# Set up logging
# The actual log file will be managed by the start.sh script via redirection
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('dashboard')

# Log startup message
logger.info("----- Dashboard starting up -----")

# Set up Flask app
app = Flask(__name__, template_folder='templates')
app.secret_key = 'quickdeploy_secret_key'
API_URL = "http://localhost:8000"

# Configuration
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
INGRESS_PORT = 8090
POLLING_INTERVAL = 2  # seconds

# Get the project root directory
if __package__ is None or __package__ == '':
    # Called directly
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
else:
    # Called as module
    parts = __package__.split('.')
    project_root = os.path.abspath(os.path.join(*([os.path.dirname(__file__)] + ['..'] * len(parts))))

# Connect to Redis
try:
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
    redis_client.ping()
    logger.info("Connected to Redis successfully")
except Exception as e:
    logger.warning(f"Redis connection error: {e}")
    redis_client = None

# In-memory cache for deployments to reduce API load
deployments_cache = {
    'data': [],
    'last_updated': 0
}

def background_poller():
    """Background thread to poll for deployment updates"""
    logger.info("Background poller thread started")
    while True:
        try:
            update_deployments_cache(force=True)
            time.sleep(POLLING_INTERVAL)
        except Exception as e:
            logger.error(f"Error in background poller: {e}")
            time.sleep(POLLING_INTERVAL)

def update_deployments_cache(force=False):
    """Update the deployments cache from the API"""
    current_time = time.time()
    if force or (current_time - deployments_cache['last_updated'] > POLLING_INTERVAL):
        try:
            response = requests.get(f"{API_URL}/deployments/")
            if response.status_code == 200:
                deployments_cache['data'] = response.json().get('deployments', [])
                deployments_cache['last_updated'] = current_time
                logger.debug(f"Updated cache with {len(deployments_cache['data'])} deployments")
                return True
        except Exception as e:
            logger.error(f"Failed to update deployments cache: {e}")
    return False

@app.route('/')
def index():
    """Dashboard home page"""
    try:
        response = requests.get(f"{API_URL}/projects/")
        if response.status_code == 200:
            projects = response.json().get('projects', [])
        else:
            projects = []
            flash('Failed to fetch projects', 'error')
    except Exception as e:
        projects = []
        flash(f'Error connecting to API: {e}', 'error')
    
    deployments = deployments_cache['data']
    
    return render_template('index.html', deployments=deployments, projects=projects)

@app.route('/projects')
def projects():
    """Projects page"""
    try:
        response = requests.get(f"{API_URL}/projects/")
        if response.status_code == 200:
            projects = response.json().get('projects', [])
        else:
            projects = []
            flash('Failed to fetch projects', 'error')
    except Exception as e:
        projects = []
        flash(f'Error connecting to API: {e}', 'error')
    
    return render_template('projects.html', projects=projects)

@app.route('/projects/new', methods=['GET', 'POST'])
def new_project():
    """Create new project page"""
    if request.method == 'POST':
        try:
            response = requests.post(
                f"{API_URL}/projects/",
                json={
                    "name": request.form.get('name'),
                    "repository_url": request.form.get('repository_url')
                }
            )
            
            if response.status_code == 200:
                flash('Project created successfully', 'success')
                return redirect(url_for('projects'))
            else:
                flash(f'Failed to create project: {response.text}', 'error')
        except Exception as e:
            flash(f'Error connecting to API: {e}', 'error')
    
    return render_template('new_project.html')

@app.route('/deployments')
def deployments():
    """Deployments page"""
    try:
        update_deployments_cache(force=True)
    except Exception as e:
        flash(f'Error refreshing deployment data: {e}', 'error')
    
    return render_template('deployments.html', deployments=deployments_cache['data'], ingress_port=INGRESS_PORT)

@app.route('/api/deployments/refresh')
def refresh_deployments():
    """API endpoint to refresh deployments data"""
    try:
        if update_deployments_cache(force=True):
            return jsonify({"success": True, "count": len(deployments_cache['data'])})
        else:
            return jsonify({"success": False, "error": "Failed to update cache"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/deployments/<deployment_id>')
def deployment_details(deployment_id):
    """Deployment details page"""
    logger.info(f"Accessing deployment details for ID: {deployment_id}")
    
    # Get the deployment from the API
    try:
        response = requests.get(f"{API_URL}/deployments/{deployment_id}")
        if response.status_code == 200:
            deployment = response.json()
            logger.info(f"API returned deployment {deployment_id} with status '{deployment['status']}'")
            
            # Parse service URLs if available
            service_urls = {}
            if deployment['url']:
                try:
                    service_urls = json.loads(deployment['url'])
                    logger.info(f"Parsed URLs: {service_urls}")
                except Exception as json_error:
                    logger.error(f"Error parsing URL JSON: {json_error}")
                    # If not JSON, treat as a single URL
                    service_urls = {'main': deployment['url']}
            
            # Add cache control headers
            response = make_response(render_template('deployment_details.html', 
                                    deployment=deployment, 
                                    service_urls=service_urls, 
                                    ingress_port=INGRESS_PORT))
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response
        else:
            logger.error(f"API returned error for deployment {deployment_id}: {response.text}")
            flash(f'Failed to fetch deployment: {response.text}', 'error')
    except Exception as e:
        logger.error(f"Error connecting to API: {e}")
        flash(f'Error connecting to API: {e}', 'error')
    
    # Return error template if we can't get the deployment
    response = make_response(render_template('deployment_details.html', 
                            deployment=None, 
                            service_urls={}, 
                            ingress_port=INGRESS_PORT))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

@app.route('/api/deployments/<deployment_id>', methods=['DELETE'])
def delete_deployment_api(deployment_id):
    """Delete a deployment via API"""
    try:
        response = requests.delete(f"{API_URL}/deployments/{deployment_id}")
        if response.status_code == 200:
            update_deployments_cache()
            return jsonify({"success": True, "message": "Deployment deleted successfully"})
        else:
            return jsonify({"success": False, "message": response.text}), response.status_code
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/deploy', methods=['GET', 'POST'])
def new_deployment():
    """Create new deployment page"""
    if request.method == 'POST':
        try:
            response = requests.post(
                f"{API_URL}/deployments/",
                json={
                    "repository": request.form.get('repository'),
                    "branch": request.form.get('branch', 'main'),
                    "commit_hash": request.form.get('commit_hash', 'HEAD')
                }
            )
            
            if response.status_code == 200:
                deployment = response.json()
                flash('Deployment created successfully', 'success')
                
                update_deployments_cache()
                
                return redirect(url_for('deployment_details', deployment_id=deployment['id']))
            else:
                flash(f'Failed to create deployment: {response.text}', 'error')
        except Exception as e:
            flash(f'Error connecting to API: {e}', 'error')
    
    # Get projects for dropdown
    try:
        response = requests.get(f"{API_URL}/projects/")
        if response.status_code == 200:
            projects = response.json().get('projects', [])
        else:
            projects = []
    except Exception as e:
        projects = []
        flash(f'Error fetching projects: {e}', 'error')
    
    return render_template('new_deployment.html', projects=projects)

@app.template_filter('format_date')
def format_date(value):
    """Format ISO date string to readable format"""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return value

@app.template_filter('status_color')
def status_color(status):
    """Return Bootstrap color class based on deployment status"""
    if status == 'deployed':
        return 'success'
    elif status == 'building' or status == 'queued':
        return 'warning'
    elif status == 'deleted':
        return 'secondary'
    else:
        return 'danger'

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    if not os.path.exists(template_dir):
        os.makedirs(template_dir)
        logger.info(f"Created templates directory at {template_dir}")
    
    # Start background polling thread
    poller_thread = threading.Thread(target=background_poller, daemon=True)
    poller_thread.start()
    
    # Run the app
    logger.info(f"Dashboard starting on http://0.0.0.0:8080")
    app.run(host='0.0.0.0', port=8080, debug=True, use_reloader=False)