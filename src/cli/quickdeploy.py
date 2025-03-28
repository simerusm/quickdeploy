#!/usr/bin/env python3
# quickdeploy.py - CLI tool for QuickDeploy on macOS
import argparse
import requests
import json
import os
import sys
import subprocess
import tempfile
import shutil
from tabulate import tabulate
from rich.console import Console
from rich.progress import Progress
from rich.panel import Panel

# Configuration
API_URL = "http://localhost:8000"
console = Console()

def create_project(args):
    """Create a new project"""
    with console.status("[bold green]Creating project..."):
        response = requests.post(
            f"{API_URL}/projects/",
            json={"name": args.name, "repository_url": args.repository}
        )
    
    if response.status_code == 200:
        project = response.json()
        console.print(f"[bold green]Project created successfully![/]")
        console.print(f"ID: {project['id']}")
        console.print(f"Name: {project['name']}")
        console.print(f"Repository: {args.repository}")
    else:
        console.print(f"[bold red]Error creating project: {response.text}[/]")

def list_projects(args):
    """List all projects"""
    with console.status("[bold green]Fetching projects..."):
        response = requests.get(f"{API_URL}/projects/")
    
    if response.status_code == 200:
        projects = response.json()["projects"]
        if not projects:
            console.print("[yellow]No projects found.[/]")
            return
        
        table_data = [
            [p["id"], p["name"], p["repository_url"], p["created_at"]]
            for p in projects
        ]
        
        console.print(tabulate(
            table_data,
            headers=["ID", "Name", "Repository", "Created At"],
            tablefmt="grid"
        ))
    else:
        console.print(f"[bold red]Error fetching projects: {response.text}[/]")

def deploy(args):
    """Deploy a project or branch"""
    # If a directory is provided, deploy from local
    if args.directory:
        deploy_local(args)
        return
    
    # Otherwise deploy from Git
    with console.status("[bold green]Creating deployment..."):
        response = requests.post(
            f"{API_URL}/deployments/",
            json={
                "repository": args.repository,
                "branch": args.branch,
                "commit_hash": args.commit or "HEAD"
            }
        )
    
    if response.status_code == 200:
        deployment = response.json()
        console.print(f"[bold green]Deployment queued successfully![/]")
        console.print(f"ID: {deployment['id']}")
        console.print(f"Status: {deployment['status']}")
        console.print(f"Repository: {deployment['repository']}")
        console.print(f"Created At: {deployment['created_at']}")
        console.print("\n[bold yellow]Deployment is processing in the background.[/]")
        console.print(f"Check status with: quickdeploy status {deployment['id']}")
    else:
        console.print(f"[bold red]Error creating deployment: {response.text}[/]")

def deploy_local(args):
    """Deploy from a local directory"""
    directory = os.path.abspath(args.directory)
    
    if not os.path.isdir(directory):
        console.print(f"[bold red]Error: {directory} is not a directory[/]")
        return
    
    # Create temporary directory for deployment
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Copy files to temp directory
        with console.status("[bold green]Preparing local files..."):
            shutil.copytree(directory, temp_dir, dirs_exist_ok=True)
        
        # Create a temporary local git repository
        with console.status("[bold green]Creating temporary git repository..."):
            subprocess.run(["git", "init"], cwd=temp_dir, check=True, stdout=subprocess.PIPE)
            subprocess.run(["git", "add", "."], cwd=temp_dir, check=True, stdout=subprocess.PIPE)
            subprocess.run(
                ["git", "config", "user.email", "quickdeploy@example.com"], 
                cwd=temp_dir, check=True, stdout=subprocess.PIPE
            )
            subprocess.run(
                ["git", "config", "user.name", "QuickDeploy"], 
                cwd=temp_dir, check=True, stdout=subprocess.PIPE
            )
            subprocess.run(
                ["git", "commit", "-m", "Local deployment"], 
                cwd=temp_dir, check=True, stdout=subprocess.PIPE
            )
        
        # Get the commit hash
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], 
            cwd=temp_dir, check=True, stdout=subprocess.PIPE, text=True
        )
        commit_hash = result.stdout.strip()
        
        # Create deployment
        with console.status("[bold green]Creating deployment..."):
            response = requests.post(
                f"{API_URL}/deployments/",
                json={
                    "repository": f"file://{temp_dir}",
                    "branch": "main",
                    "commit_hash": commit_hash
                }
            )
        
        if response.status_code == 200:
            deployment = response.json()
            console.print(f"[bold green]Local deployment queued successfully![/]")
            console.print(f"ID: {deployment['id']}")
            console.print(f"Status: {deployment['status']}")
            console.print(f"Created At: {deployment['created_at']}")
            console.print("\n[bold yellow]Deployment is processing in the background.[/]")
            console.print(f"Check status with: quickdeploy status {deployment['id']}")
        else:
            console.print(f"[bold red]Error creating deployment: {response.text}[/]")
    
    except Exception as e:
        console.print(f"[bold red]Error: {str(e)}[/]")
    
    # Don't remove temp_dir as it's needed for the build

def list_deployments(args):
    """List all deployments"""
    with console.status("[bold green]Fetching deployments..."):
        response = requests.get(f"{API_URL}/deployments/")
    
    if response.status_code == 200:
        deployments = response.json()["deployments"]
        if not deployments:
            console.print("[yellow]No deployments found.[/]")
            return
        
        table_data = [
            [
                d["id"], 
                d["repository"].split('/')[-1], 
                d["branch"], 
                d["status"], 
                d["url"] or "N/A", 
                d["created_at"]
            ]
            for d in deployments
        ]
        
        console.print(tabulate(
            table_data,
            headers=["ID", "Repository", "Branch", "Status", "URL", "Created At"],
            tablefmt="grid"
        ))
    else:
        console.print(f"[bold red]Error fetching deployments: {response.text}[/]")

def get_deployment_status(args):
    """Get status of a specific deployment"""
    with console.status(f"[bold green]Fetching deployment {args.id}..."):
        response = requests.get(f"{API_URL}/deployments/{args.id}")
    
    if response.status_code == 200:
        deployment = response.json()
        console.print(f"[bold]Deployment: {deployment['id']}[/]")
        console.print(f"Repository: {deployment['repository']}")
        console.print(f"Branch: {deployment['branch']}")
        console.print(f"Commit: {deployment['commit_hash']}")
        
        status = deployment['status']
        if status == "deployed":
            console.print(f"Status: [bold green]{status}[/]")
        elif status == "building" or status == "queued":
            console.print(f"Status: [bold yellow]{status}[/]")
        else:
            console.print(f"Status: [bold red]{status}[/]")
            
        if deployment['url']:
            console.print(f"URL: [link={deployment['url']}]{deployment['url']}[/link]")
        console.print(f"Created: {deployment['created_at']}")
        console.print(f"Updated: {deployment['updated_at']}")
    else:
        console.print(f"[bold red]Error fetching deployment: {response.text}[/]")

def create_stack(args):
    """Create a new stack"""
    with console.status("[bold green]Creating stack..."):
        response = requests.post(
            f"{API_URL}/stacks/",
            json={"name": args.name, "description": args.description}
        )
    
    if response.status_code == 200:
        stack = response.json()
        console.print(f"[bold green]Stack created successfully![/]")
        console.print(f"ID: {stack['id']}")
        console.print(f"Name: {stack['name']}")
    else:
        console.print(f"[bold red]Error creating stack: {response.text}[/]")

def list_stacks(args):
    """List all stacks"""
    with console.status("[bold green]Fetching stacks..."):
        response = requests.get(f"{API_URL}/stacks/")
    
    if response.status_code == 200:
        stacks = response.json()["stacks"]
        if not stacks:
            console.print("[yellow]No stacks found.[/]")
            return
        
        table_data = [
            [s["id"], s["name"], s["description"], s["created_at"]]
            for s in stacks
        ]
        
        console.print(tabulate(
            table_data,
            headers=["ID", "Name", "Description", "Created At"],
            tablefmt="grid"
        ))
    else:
        console.print(f"[bold red]Error fetching stacks: {response.text}[/]")

def get_stack(args):
    """Get details for a specific stack"""
    with console.status(f"[bold green]Fetching stack {args.id}..."):
        response = requests.get(f"{API_URL}/stacks/{args.id}")
    
    if response.status_code == 200:
        stack = response.json()
        console.print(Panel(f"[bold]{stack['name']}[/]", subtitle=f"ID: {stack['id']}"))
        console.print(f"Description: {stack['description']}")
        console.print(f"Created: {stack['created_at']}")
        
        if "services" in stack and stack["services"]:
            console.print("\n[bold]Services:[/]")
            
            table_data = [
                [s["id"], s["service_name"], s["service_type"], s["repository"]]
                for s in stack["services"]
            ]
            
            console.print(tabulate(
                table_data,
                headers=["ID", "Name", "Type", "Repository"],
                tablefmt="grid"
            ))
        else:
            console.print("\n[yellow]No services in this stack. Add services with:[/]")
            console.print(f"quickdeploy stack add-service {stack['id']} <name> <repository>")
    else:
        console.print(f"[bold red]Error fetching stack: {response.text}[/]")

def add_service(args):
    """Add a service to a stack"""
    service_data = {
        "stack_id": args.stack_id,
        "service_name": args.name,
        "repository": args.repository,
        "service_type": args.type,
        "configuration": {}
    }
    
    # Parse configuration if provided
    if args.config:
        try:
            service_data["configuration"] = json.loads(args.config)
        except json.JSONDecodeError:
            console.print("[bold red]Error: Configuration must be valid JSON[/]")
            return
    
    with console.status("[bold green]Adding service to stack..."):
        response = requests.post(
            f"{API_URL}/stacks/{args.stack_id}/services",
            json=service_data
        )
    
    if response.status_code == 200:
        service = response.json()
        console.print(f"[bold green]Service added successfully![/]")
        console.print(f"ID: {service['id']}")
        console.print(f"Name: {service['service_name']}")
        console.print(f"Stack ID: {service['stack_id']}")
    else:
        console.print(f"[bold red]Error adding service: {response.text}[/]")

def deploy_stack(args):
    """Deploy an entire stack"""
    with console.status(f"[bold green]Deploying stack {args.id}..."):
        response = requests.post(f"{API_URL}/stacks/{args.id}/deploy")
    
    if response.status_code == 200:
        result = response.json()
        console.print(f"[bold green]Stack deployment started![/]")
        console.print(f"Stack ID: {result['stack_id']}")
        console.print(f"Deployment count: {len(result['deployments'])}")
        console.print("\n[bold yellow]Deployments are processing in the background.[/]")
        console.print(f"Check individual deployment statuses with: quickdeploy status <deployment_id>")
    else:
        console.print(f"[bold red]Error deploying stack: {response.text}[/]")

def main():
    parser = argparse.ArgumentParser(description="QuickDeploy CLI for macOS")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Project commands
    project_parser = subparsers.add_parser("project", help="Manage projects")
    project_subparsers = project_parser.add_subparsers(dest="project_command")
    
    # Create project
    create_project_parser = project_subparsers.add_parser("create", help="Create a new project")
    create_project_parser.add_argument("name", help="Project name")
    create_project_parser.add_argument("repository", help="Git repository URL")
    create_project_parser.set_defaults(func=create_project)
    
    # List projects
    list_projects_parser = project_subparsers.add_parser("list", help="List all projects")
    list_projects_parser.set_defaults(func=list_projects)
    
    # Deploy command
    deploy_parser = subparsers.add_parser("deploy", help="Deploy a project")
    deploy_parser.add_argument("--repository", "-r", help="Git repository URL")
    deploy_parser.add_argument("--branch", "-b", default="main", help="Git branch (default: main)")
    deploy_parser.add_argument("--commit", "-c", help="Git commit hash (default: HEAD)")
    deploy_parser.add_argument("--directory", "-d", help="Local directory to deploy")
    deploy_parser.set_defaults(func=deploy)
    
    # Deployment commands
    deployments_parser = subparsers.add_parser("deployments", help="List deployments")
    deployments_parser.set_defaults(func=list_deployments)
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Get deployment status")
    status_parser.add_argument("id", help="Deployment ID")
    status_parser.set_defaults(func=get_deployment_status)
    
    # Stack commands
    stack_parser = subparsers.add_parser("stack", help="Manage microservice stacks")
    stack_subparsers = stack_parser.add_subparsers(dest="stack_command")
    
    # Create stack
    create_stack_parser = stack_subparsers.add_parser("create", help="Create a new stack")
    create_stack_parser.add_argument("name", help="Stack name")
    create_stack_parser.add_argument("--description", "-d", default="", help="Stack description")
    create_stack_parser.set_defaults(func=create_stack)
    
    # List stacks
    list_stacks_parser = stack_subparsers.add_parser("list", help="List all stacks")
    list_stacks_parser.set_defaults(func=list_stacks)
    
    # Get stack
    get_stack_parser = stack_subparsers.add_parser("get", help="Get stack details")
    get_stack_parser.add_argument("id", help="Stack ID")
    get_stack_parser.set_defaults(func=get_stack)
    
    # Add service
    add_service_parser = stack_subparsers.add_parser("add-service", help="Add service to stack")
    add_service_parser.add_argument("stack_id", help="Stack ID")
    add_service_parser.add_argument("name", help="Service name")
    add_service_parser.add_argument("repository", help="Git repository URL")
    add_service_parser.add_argument("--type", "-t", default="web", 
                                   help="Service type (web, api, db, cache)")
    add_service_parser.add_argument("--config", "-c", help="Configuration JSON")
    add_service_parser.set_defaults(func=add_service)
    
    # Deploy stack
    deploy_stack_parser = stack_subparsers.add_parser("deploy", help="Deploy entire stack")
    deploy_stack_parser.add_argument("id", help="Stack ID")
    deploy_stack_parser.set_defaults(func=deploy_stack)
    
    args = parser.parse_args()
    
    # Show QuickDeploy banner
    console.print(Panel.fit(
        "[bold cyan]QuickDeploy[/] - Local Microservices Deployment Platform",
        subtitle="For macOS with Docker Desktop"
    ))
    
    if not args.command:
        parser.print_help()
        return
    
    if hasattr(args, 'func'):
        args.func(args)
    elif args.command == "project" and not args.project_command:
        project_parser.print_help()
    elif args.command == "stack" and not args.stack_command:
        stack_parser.print_help()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()