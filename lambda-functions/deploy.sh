#!/bin/bash

# Qila Service Deployment Script
# This script ensures shared utilities are copied to Lambda functions before deployment

set -e  # Exit on any error

echo "🚀 Starting Qila Service Deployment..."

# Check if we're in the right directory
if [ ! -f "template.yaml" ]; then
    echo "❌ Error: template.yaml not found. Please run this script from the lambda-functions directory."
    exit 1
fi

# Copy shared utilities to each Lambda function
echo "📁 Copying shared utilities to Lambda functions..."

if [ -d "shared/python" ]; then
    echo "  → Copying to webhook-handler/"
    cp -f shared/python/*.py webhook-handler/ 2>/dev/null || echo "    Warning: No Python files found in shared/python/"
    
    echo "  → Copying to background-processor/"
    cp -f shared/python/*.py background-processor/ 2>/dev/null || echo "    Warning: No Python files found in shared/python/"
else
    echo "❌ Error: shared/python directory not found!"
    exit 1
fi

echo "✅ Shared utilities copied successfully!"

# Build the SAM application
echo "🔨 Building SAM application..."
sam build

if [ $? -ne 0 ]; then
    echo "❌ SAM build failed!"
    exit 1
fi

echo "✅ Build completed successfully!"

# Deploy based on provided arguments
if [ "$1" = "--guided" ]; then
    echo "🚀 Running guided deployment..."
    sam deploy --guided
elif [ "$1" = "--deploy" ]; then
    echo "🚀 Deploying with existing configuration..."
    sam deploy
else
    echo "✅ Build complete! Ready for deployment."
    echo ""
    echo "Next steps:"
    echo "  - For first-time deployment: ./deploy.sh --guided"
    echo "  - For subsequent deployments: ./deploy.sh --deploy"
    echo "  - Or run manually: sam deploy"
fi

echo "🎉 Deployment process completed!"