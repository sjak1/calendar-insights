from mangum import Mangum
from api import app
from logging_config import setup_logging
import os

# Configure logging for Lambda environment
# Lambda automatically sends stdout/stderr to CloudWatch Logs
# Log group: /aws/lambda/<function-name>
setup_logging(
    log_level=os.getenv("LOG_LEVEL", "INFO"),  # Can override with env var
    enable_file_logging=False,  # No file system access in Lambda
    enable_console_logging=True  # Console logs go to CloudWatch
)

# Get logger to confirm setup
logger = setup_logging()
logger.info("🚀 Lambda handler initialized - logs will appear in CloudWatch")

handler = Mangum(app)  