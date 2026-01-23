#!/bin/bash
set -e

echo "🧹 cleaning..."
rm -rf build lambda_deployment.zip
mkdir -p build

echo "📦 installing deps (python3.13, linux)..."
docker run --rm --platform linux/amd64 \
  -v "$PWD":/var/task \
  -w /var/task \
  --entrypoint /bin/bash \
  public.ecr.aws/lambda/python:3.13 \
  -c "pip install -r requirements.txt -t /var/task/build"

echo "📋 copying source..."
cp api.py query_processor.py lambda_handler.py logging_config.py session_manager.py build/
mkdir -p build/scripts
cp scripts/sqlite_qa.py build/scripts/
[ -f scripts/__init__.py ] && cp scripts/__init__.py build/scripts/ || touch build/scripts/__init__.py
cp -r tools/ build/
cp -r utils/ build/

echo "📦 zipping..."
cd build
zip -r ../lambda_deployment.zip . -q
cd ..

echo "✅ done. package:"
ls -lh lambda_deployment.zip

echo "🚀 upload lambda_deployment.zip to aws"
