"""
Centralized logging configuration for the Calendar Insights project.

This module provides a consistent logging setup across the application,
supporting both local development and AWS Lambda deployment.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional


def setup_logging(
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    enable_file_logging: bool = True,
    enable_console_logging: bool = True,
) -> logging.Logger:
    """
    Configure logging for the application.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
                   Defaults to INFO, or DEBUG if LOG_LEVEL env var is set.
        log_file: Path to log file. Defaults to 'logs/app.log'.
        enable_file_logging: Whether to log to file. Defaults to True.
        enable_console_logging: Whether to log to console. Defaults to True.
    
    Returns:
        Configured root logger instance.
    """
    # Check if we're in Lambda environment
    is_lambda = bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
    
    # In Lambda, disable file logging automatically (filesystem is read-only except /tmp)
    if is_lambda:
        enable_file_logging = False
    
    # Determine log level from environment or parameter
    if log_level is None:
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    # Convert string to logging level constant
    numeric_level = getattr(logging, log_level, logging.INFO)
    
    # Create logs directory if it doesn't exist (only if not in Lambda)
    if enable_file_logging and not is_lambda:
        if log_file is None:
            log_file = os.getenv("LOG_FILE", "logs/app.log")
        
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)
            except OSError as e:
                # If we can't create the directory (e.g., read-only filesystem),
                # fall back to console-only logging
                enable_file_logging = False
                logging.warning(f"Could not create log directory {log_dir}: {e}. Falling back to console logging.")
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Clear existing handlers to avoid duplicates
    root_logger.handlers.clear()
    
    # Create formatter
    detailed_formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Console handler with simpler format
    if enable_console_logging:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_formatter = logging.Formatter(
            fmt="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
            datefmt="%H:%M:%S"
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
    
    # File handler with rotation
    if enable_file_logging and log_file:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(file_handler)
    
    # Configure third-party loggers
    # Reduce noise from external libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    
    # Lambda environment: log that we're using CloudWatch
    if is_lambda:
        root_logger.info("Running in AWS Lambda environment - using CloudWatch for logs")
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module.
    
    Args:
        name: Logger name (typically __name__ of the calling module)
    
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# Initialize logging when module is imported
# This can be overridden by calling setup_logging() explicitly
if not logging.getLogger().handlers:
    # Check if we're in Lambda
    is_lambda = bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
    setup_logging(
        enable_file_logging=not is_lambda,  # No file logging in Lambda
        enable_console_logging=True
    )

