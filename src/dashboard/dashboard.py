# dashboard.py - Simple web dashboard using Flask
from flask import Flask, render_template, request, redirect, url_for, flash
import requests
import json
from datetime import datetime

app = Flask(__name__, template_folder='templates')
app.secret_key = 'quickdeploy_secret_key'  # For flash messages
API_URL = "http://localhost:8000"

INGRESS_PORT = 8090

@app.route('/')
def index():
    """Dashboard home page"""
    # Get deployments
    response = requests.get(f"{API_URL}/deployments/")
    if response.status_code == 200:
        deployments = response.json().get('deployments', [])
    else:
        deployments = []
        flash('Failed to fetch deployments', 'error')
    
    # Get projects
    response = requests.get(f"{API_URL}/projects/")
    if response.status_code == 200:
        projects = response.json().get('projects', [])
    else:
        projects = []
        flash('Failed to fetch projects', 'error')
    
    return render_template('index.html', deployments=deployments, projects=projects)

@app.route('/projects')
def projects():
    """Projects page"""
    response = requests.get(f"{API_URL}/projects/")
    if response.status_code == 200:
        projects = response.json().get('projects', [])
    else:
        projects = []
        flash('Failed to fetch projects', 'error')
    
    return render_template('projects.html', projects=projects)

@app.route('/projects/new', methods=['GET', 'POST'])
def new_project():
    """Create new project page"""
    if request.method == 'POST':
        # Create project
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
    
    return render_template('new_project.html')

@app.route('/deployments')
def deployments():
    """Deployments page"""
    response = requests.get(f"{API_URL}/deployments/")
    if response.status_code == 200:
        deployments = response.json().get('deployments', [])
    else:
        deployments = []
        flash('Failed to fetch deployments', 'error')
    
    return render_template('deployments.html', deployments=deployments)

@app.route('/deployments/<deployment_id>')
def deployment_details(deployment_id):
    """Deployment details page"""
    response = requests.get(f"{API_URL}/deployments/{deployment_id}")
    if response.status_code == 200:
        deployment = response.json()
    else:
        deployment = None
        flash('Failed to fetch deployment details', 'error')
    
    return render_template('deployment_details.html', deployment=deployment, ingress_port=INGRESS_PORT)

@app.route('/deploy', methods=['GET', 'POST'])
def new_deployment():
    """Create new deployment page"""
    if request.method == 'POST':
        # Create deployment
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
            return redirect(url_for('deployment_details', deployment_id=deployment['id']))
        else:
            flash(f'Failed to create deployment: {response.text}', 'error')
    
    # Get projects for dropdown
    response = requests.get(f"{API_URL}/projects/")
    if response.status_code == 200:
        projects = response.json().get('projects', [])
    else:
        projects = []
    
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
    else:
        return 'danger'

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    import os
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    # Create basic templates
    with open('templates/base.html', 'w') as f:
        f.write('''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}QuickDeploy{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { padding-top: 56px; }
        .bd-placeholder-img { font-size: 1.125rem; text-anchor: middle; }
        .status-badge { font-size: 0.8rem; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-md navbar-dark fixed-top bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand" href="/">QuickDeploy</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarCollapse" aria-controls="navbarCollapse" aria-expanded="false" aria-label="Toggle navigation">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarCollapse">
                <ul class="navbar-nav me-auto mb-2 mb-md-0">
                    <li class="nav-item">
                        <a class="nav-link" href="/">Dashboard</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/projects">Projects</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/deployments">Deployments</a>
                    </li>
                </ul>
                <div class="d-flex">
                    <a href="/deploy" class="btn btn-success">Deploy</a>
                </div>
            </div>
        </div>
    </nav>

    <main class="container mt-4">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category if category != 'error' else 'danger' }}">
                        {{ message }}
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        {% block content %}{% endblock %}
    </main>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
        ''')
    
    with open('templates/index.html', 'w') as f:
        f.write('''
{% extends "base.html" %}
{% block title %}QuickDeploy - Dashboard{% endblock %}
{% block content %}
<div class="row">
    <div class="col-md-12">
        <h1>Dashboard</h1>
        <div class="row mt-4">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0">Recent Deployments</h5>
                        <a href="/deployments" class="btn btn-sm btn-outline-primary">View All</a>
                    </div>
                    <div class="card-body">
                        {% if deployments %}
                            <table class="table table-striped">
                                <thead>
                                    <tr>
                                        <th>Repository</th>
                                        <th>Status</th>
                                        <th>Created</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for deployment in deployments[:5] %}
                                    <tr>
                                        <td>
                                            <a href="/deployments/{{ deployment.id }}">
                                                {{ deployment.repository.split('/')[-1] }}
                                            </a>
                                        </td>
                                        <td>
                                            <span class="badge bg-{{ deployment.status|status_color }}">
                                                {{ deployment.status }}
                                            </span>
                                        </td>
                                        <td>{{ deployment.created_at|format_date }}</td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        {% else %}
                            <p class="text-muted">No deployments yet.</p>
                        {% endif %}
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0">Projects</h5>
                        <a href="/projects/new" class="btn btn-sm btn-outline-primary">New Project</a>
                    </div>
                    <div class="card-body">
                        {% if projects %}
                            <table class="table table-striped">
                                <thead>
                                    <tr>
                                        <th>Name</th>
                                        <th>Repository</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for project in projects %}
                                    <tr>
                                        <td>{{ project.name }}</td>
                                        <td>{{ project.repository_url }}</td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        {% else %}
                            <p class="text-muted">No projects yet.</p>
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
        ''')
        
    app.run(host='0.0.0.0', port=8080, debug=True)
    print(f"Dashboard starting on http://0.0.0.0:8080")