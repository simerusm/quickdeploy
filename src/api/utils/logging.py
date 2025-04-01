import logging
import os

def setup_logging():
    """Configure logging for QuickDeploy"""
    log_dir = "../../logs"
    
    # Ensure log directory exists
    os.makedirs(log_dir, exist_ok=True)
    
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(log_dir, "worker.log")),
            logging.StreamHandler()
        ]
    )
    
    # Create and return logger
    logger = logging.getLogger('quickdeploy')
    logger.info("QuickDeploy logging initialized")
    return logger