import os
import shutil
import subprocess
import logging

logger = logging.getLogger('quickdeploy')

def clone_repository(repo_url, branch, temp_dir):
    """Clone git repository to temporary directory"""
    try:
        # Check if it's a local file URL
        if repo_url.startswith("file://"):
            local_path = repo_url[7:]  # Remove "file://" prefix
            if os.path.isdir(local_path):
                # Copy files to temp directory
                for item in os.listdir(local_path):
                    source = os.path.join(local_path, item)
                    dest = os.path.join(temp_dir, item)
                    if os.path.isdir(source):
                        shutil.copytree(source, dest)
                    else:
                        shutil.copy2(source, dest)
                logger.info(f"Copied local directory {local_path} to {temp_dir}")
                return True
            else:
                logger.error(f"Local directory {local_path} does not exist")
                return False
        else:
            # Normal git clone
            logger.info(f"Cloning repository {repo_url} branch {branch}...")
            result = subprocess.run(
                ["git", "clone", "--branch", branch, repo_url, temp_dir],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE # stdout captured by pipe instead of printing to console
            )
            logger.info("Clone completed successfully")
            return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Git clone error: {e}")
        logger.error(f"Error output: {e.stderr.decode() if e.stderr else 'None'}")
        return False
    except Exception as e:
        logger.error(f"Clone error: {e}")
        return False

def find_files(directory, filename_patterns):
    """Find files matching any of the patterns in the directory"""
    matching_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if any(pattern in file for pattern in filename_patterns):
                matching_files.append(os.path.join(root, file))
    return matching_files

def write_env_file(filepath, variables):
    """Write environment variables to a file"""
    with open(filepath, "w") as f:
        for key, value in variables.items():
            f.write(f"{key}={value}\n")
    logger.info(f"Created environment file at {filepath}")