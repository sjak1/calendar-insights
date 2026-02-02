"""Logging config for both local and Lambda environments."""

import logging
import os
import sys

# Silence noisy third-party libraries
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

# Check if running in Lambda
IS_LAMBDA = os.getenv("AWS_LAMBDA_FUNCTION_NAME") is not None

def setup_logging(log_level="INFO", enable_file_logging=True, enable_console_logging=True):
    """
    Setup logging for the application.
    
    In Lambda: All logs go to stdout/stderr which CloudWatch captures automatically.
    Locally: Can write to file and/or console.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        enable_file_logging: Enable file logging (ignored in Lambda)
        enable_console_logging: Enable console logging
    """
    # Get log level from env or parameter
    level = os.getenv("LOG_LEVEL", log_level).upper()
    log_level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
    }
    numeric_level = log_level_map.get(level, logging.INFO)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()
    
    # Format for logs
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%H:%M:%S"
    )
    
    # In Lambda: Only console (stdout/stderr) - CloudWatch captures this automatically
    if IS_LAMBDA:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        root_logger.info(f"🔧 Lambda environment detected - logs will appear in CloudWatch: /aws/lambda/{os.getenv('AWS_LAMBDA_FUNCTION_NAME', 'unknown')}")
    else:
        # Local: Console handler
        if enable_console_logging:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(numeric_level)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)
        
        # Local: File handler (if enabled)
        if enable_file_logging:
            log_dir = os.path.join(os.path.dirname(__file__), "logs")
            os.makedirs(log_dir, exist_ok=True)
            file_handler = logging.FileHandler(
                os.path.join(log_dir, "app.log"),
                encoding="utf-8"
            )
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a module."""
    return logging.getLogger(name)
