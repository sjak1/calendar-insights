from mangum import Mangum
from api import app
from logging_config import setup_logging

# Configure logging for Lambda environment
# Lambda automatically sends stdout/stderr to CloudWatch
setup_logging(
    log_level="INFO",  # Use INFO for Lambda to reduce noise
    enable_file_logging=False,  # No file system access in Lambda
    enable_console_logging=True  # Console logs go to CloudWatch
)

handler = Mangum(app)  