# Use AWS Lambda Python base image
FROM public.ecr.aws/lambda/python:3.12

WORKDIR ${LAMBDA_TASK_ROOT}

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (only what we need)
COPY api.py bedrock_llm.py query_processor.py lambda_handler.py logging_config.py session_manager.py database.py opensearch_client.py schema_reference.py ./
COPY scripts/ ./scripts/
COPY tools/ ./tools/
COPY utils/ ./utils/
COPY static/ ./static/

# Set the CMD to your handler
CMD [ "lambda_handler.handler" ]
