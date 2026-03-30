#!/bin/bash
# Build and deploy Lambda container image to ECR

set -e

# Configuration - UPDATE THESE
AWS_REGION="us-west-2"
AWS_ACCOUNT_ID=""  # Will be detected automatically if AWS CLI is configured
ECR_REPO_NAME="calender-insights-lambda"
LAMBDA_FUNCTION_NAME="calendar-insights-demo calendar-ai-api-1"  # space-separated list
IMAGE_TAG="latest"

# Get AWS account ID if not set
if [ -z "$AWS_ACCOUNT_ID" ]; then
    AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    if [ -z "$AWS_ACCOUNT_ID" ]; then
        echo "❌ Error: Could not get AWS account ID. Make sure AWS CLI is configured."
        exit 1
    fi
fi

ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"

echo "🔨 Building Docker image..."
DOCKER_BUILDKIT=0 docker build --platform linux/amd64 -t ${ECR_REPO_NAME}:${IMAGE_TAG} .

echo "🏷️  Tagging image for ECR..."
docker tag ${ECR_REPO_NAME}:${IMAGE_TAG} ${ECR_URI}:${IMAGE_TAG}

echo "🔐 Logging in to ECR..."
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ECR_URI}

echo "📤 Pushing image to ECR..."
docker push ${ECR_URI}:${IMAGE_TAG}

echo "✅ Image pushed! URI: ${ECR_URI}:${IMAGE_TAG}"

# Update Lambda functions
if [ -z "$LAMBDA_FUNCTION_NAME" ]; then
    echo "⚠️  No Lambda function name set. Please update manually:"
    echo "   aws lambda update-function-code --function-name YOUR_FUNCTION_NAME --image-uri ${ECR_URI}:${IMAGE_TAG} --region ${AWS_REGION}"
else
    for FN in ${LAMBDA_FUNCTION_NAME}; do
        echo "🔄 Updating Lambda function: ${FN}..."
        aws lambda update-function-code \
            --function-name ${FN} \
            --image-uri ${ECR_URI}:${IMAGE_TAG} \
            --region ${AWS_REGION} \
            --output text > /dev/null
        echo "⏳ Waiting for ${FN} to finish updating..."
        aws lambda wait function-updated --function-name ${FN} --region ${AWS_REGION}
        echo "✅ ${FN} updated!"
    done
fi