# app.py - FastAPI service for macOS
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import sqlite3
import os
import redis
import json
import uuid
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware

# Initialize FastAPI app
app = FastAPI(title="QuickDeploy API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

# Connect to Redis
try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0)
    redis_client.ping()  # Test connection
    print("Connected to Redis successfully")
except redis.ConnectionError as e:
    print(f"Redis connection error: {e}")
    print("Make sure Redis is running on localhost:6379")
    print("You can start it with: docker run -d -p 6379:6379 --name redis redis:alpine")

# Initialize SQLite database
def init_db():
    db_path = 'quickdeploy.db'
    
    # Check if the file exists
    db_exists = os.path.isfile(db_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create deployments table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS deployments (
        id TEXT PRIMARY KEY,
        repository TEXT,
        branch TEXT,
        commit_hash TEXT,
        status TEXT,
        created_at TEXT,
        updated_at TEXT,
        url TEXT
    )
    ''')
    
    # Create projects table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT,
        repository_url TEXT,
        created_at TEXT
    )
    ''')
    
    # Create stacks table for managing microservice stacks
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS stacks (
        id TEXT PRIMARY KEY,
        name TEXT,
        description TEXT,
        created_at TEXT
    )
    ''')
    
    # Create stack_services table for services that belong to a stack
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS stack_services (
        id TEXT PRIMARY KEY,
        stack_id TEXT,
        service_name TEXT,
        repository TEXT,
        service_type TEXT,
        configuration TEXT,
        FOREIGN KEY (stack_id) REFERENCES stacks (id)
    )
    ''')
    
    conn.commit()
    conn.close()
    
    if not db_exists:
        print(f"Created new database at {db_path}")
    else:
        print(f"Using existing database at {db_path}")

# Models
class Project(BaseModel):
    name: str
    repository_url: str

class Deployment(BaseModel):
    repository: str
    branch: str = "main"
    commit_hash: str = "HEAD"

class Stack(BaseModel):
    name: str
    description: str = ""

class StackService(BaseModel):
    stack_id: str
    service_name: str
    repository: str
    service_type: str = "web"
    configuration: dict = {}

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_db()

# API endpoints
@app.get("/")
def read_root():
    return {"status": "QuickDeploy API is running"}

@app.post("/projects/")
def create_project(project: Project):
    project_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat()
    
    conn = sqlite3.connect('quickdeploy.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO projects (id, name, repository_url, created_at) VALUES (?, ?, ?, ?)",
        (project_id, project.name, project.repository_url, created_at)
    )
    conn.commit()
    conn.close()
    
    return {"id": project_id, "name": project.name, "created_at": created_at}

@app.get("/projects/")
def list_projects():
    conn = sqlite3.connect('quickdeploy.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM projects")
    projects = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return {"projects": projects}

@app.post("/deployments/")
def create_deployment(deployment: Deployment, background_tasks: BackgroundTasks):
    deployment_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat()
    
    conn = sqlite3.connect('quickdeploy.db')
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO deployments 
           (id, repository, branch, commit_hash, status, created_at, updated_at, url) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (deployment_id, deployment.repository, deployment.branch, 
         deployment.commit_hash, "queued", created_at, created_at, "")
    )
    conn.commit()
    conn.close()
    
    # Add to Redis queue
    deploy_job = {
        "id": deployment_id,
        "repository": deployment.repository,
        "branch": deployment.branch,
        "commit_hash": deployment.commit_hash,
        "created_at": created_at
    }
    redis_client.lpush("build_queue", json.dumps(deploy_job))
    
    return {
        "id": deployment_id,
        "status": "queued",
        "repository": deployment.repository,
        "created_at": created_at
    }

@app.get("/deployments/")
def list_deployments():
    conn = sqlite3.connect('quickdeploy.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM deployments ORDER BY created_at DESC")
    deployments = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return {"deployments": deployments}

@app.get("/deployments/{deployment_id}")
def get_deployment(deployment_id: str):
    conn = sqlite3.connect('quickdeploy.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM deployments WHERE id = ?", (deployment_id,))
    deployment = cursor.fetchone()
    conn.close()
    
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    
    return dict(deployment)

# Stack management endpoints
@app.post("/stacks/")
def create_stack(stack: Stack):
    stack_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat()
    
    conn = sqlite3.connect('quickdeploy.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO stacks (id, name, description, created_at) VALUES (?, ?, ?, ?)",
        (stack_id, stack.name, stack.description, created_at)
    )
    conn.commit()
    conn.close()
    
    return {"id": stack_id, "name": stack.name, "created_at": created_at}

@app.get("/stacks/")
def list_stacks():
    conn = sqlite3.connect('quickdeploy.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM stacks")
    stacks = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return {"stacks": stacks}

@app.get("/stacks/{stack_id}")
def get_stack(stack_id: str):
    conn = sqlite3.connect('quickdeploy.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get stack details
    cursor.execute("SELECT * FROM stacks WHERE id = ?", (stack_id,))
    stack = cursor.fetchone()
    
    if stack is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Stack not found")
    
    # Get services in this stack
    cursor.execute("SELECT * FROM stack_services WHERE stack_id = ?", (stack_id,))
    services = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    result = dict(stack)
    result["services"] = services
    
    return result

@app.post("/stacks/{stack_id}/services")
def add_service_to_stack(stack_id: str, service: StackService):
    # Verify stack exists
    conn = sqlite3.connect('quickdeploy.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM stacks WHERE id = ?", (stack_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Stack not found")
    
    service_id = str(uuid.uuid4())
    
    # Store configuration as JSON
    configuration_json = json.dumps(service.configuration)
    
    cursor.execute(
        """INSERT INTO stack_services 
           (id, stack_id, service_name, repository, service_type, configuration) 
           VALUES (?, ?, ?, ?, ?, ?)""",
        (service_id, stack_id, service.service_name, service.repository, 
         service.service_type, configuration_json)
    )
    conn.commit()
    conn.close()
    
    return {
        "id": service_id,
        "stack_id": stack_id,
        "service_name": service.service_name
    }

@app.post("/stacks/{stack_id}/deploy")
def deploy_stack(stack_id: str, background_tasks: BackgroundTasks):
    # Verify stack exists and get services
    conn = sqlite3.connect('quickdeploy.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM stacks WHERE id = ?", (stack_id,))
    stack = cursor.fetchone()
    
    if not stack:
        conn.close()
        raise HTTPException(status_code=404, detail="Stack not found")
    
    cursor.execute("SELECT * FROM stack_services WHERE stack_id = ?", (stack_id,))
    services = cursor.fetchall()
    
    if not services:
        conn.close()
        raise HTTPException(status_code=400, detail="Stack has no services")
    
    # Create deployments for each service
    deployment_ids = []
    created_at = datetime.now().isoformat()
    
    for service in services:
        deployment_id = str(uuid.uuid4())
        cursor.execute(
            """INSERT INTO deployments 
               (id, repository, branch, commit_hash, status, created_at, updated_at, url) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (deployment_id, service["repository"], "main", "HEAD", "queued", created_at, created_at, "")
        )
        
        # Add to Redis queue
        deploy_job = {
            "id": deployment_id,
            "repository": service["repository"],
            "branch": "main",
            "commit_hash": "HEAD",
            "created_at": created_at,
            "stack_id": stack_id,
            "service_name": service["service_name"]
        }
        redis_client.lpush("build_queue", json.dumps(deploy_job))
        deployment_ids.append(deployment_id)
    
    conn.commit()
    conn.close()
    
    return {
        "stack_id": stack_id,
        "deployments": deployment_ids,
        "status": "queued"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)