# Use AWS Lambda Python base image
FROM public.ecr.aws/lambda/python:3.12

WORKDIR ${LAMBDA_TASK_ROOT}

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (only what we need)
COPY api.py get_gdp.py lambda_handler.py logging_config.py ./
COPY scripts/ ./scripts/
COPY static/ ./static/

# Set the CMD to your handler
CMD [ "lambda_handler.handler" ]
