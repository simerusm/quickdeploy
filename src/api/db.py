import sqlite3
from datetime import datetime
import json
import logging
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(current_dir, 'quickdeploy.db')

logger = logging.getLogger('quickdeploy')

def init_database():
    """Initialize the SQLite database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
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
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT,
            repository_url TEXT,
            created_at TEXT
        )
        ''')
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        return False

def update_deployment_status(deployment_id, status, url=""):
    """Update deployment status in database"""
    try:
        # Update database
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        updated_at = datetime.now().isoformat()
        
        print(f"DB: Updating deployment {deployment_id} to status={status}, url={url}")
        cursor.execute(
            "UPDATE deployments SET status = ?, updated_at = ?, url = ? WHERE id = ?",
            (status, updated_at, url, deployment_id)
        )
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        print(f"DB: Update complete, {rows_affected} rows affected")
        logger.info(f"Updated deployment {deployment_id} status to {status}")
            
    except Exception as e:
        print(f"DB UPDATE ERROR: {e}")
        logger.error(f"Error updating deployment status: {e}")