#!/bin/bash
# Create ECR repository for Lambda container image

set -e

AWS_REGION="us-west-2"
ECR_REPO_NAME="calender-insights-lambda"

echo "🔨 Creating ECR repository: ${ECR_REPO_NAME}..."

aws ecr create-repository \
    --repository-name ${ECR_REPO_NAME} \
    --region ${AWS_REGION} \
    --image-scanning-configuration scanOnPush=true \
    --image-tag-mutability MUTABLE 2>/dev/null || echo "⚠️  Repository might already exist (that's okay)"

echo "✅ ECR repository ready!"
echo ""
echo "📋 Repository URI:"
aws ecr describe-repositories --repository-names ${ECR_REPO_NAME} --region ${AWS_REGION} --query 'repositories[0].repositoryUri' --output text

