#!/bin/bash
# Deploy all Lambda functions to AWS

set -e  # Exit on error

echo "🚀 Deploying all Lambda functions to AWS..."
echo ""

# Check if AWS CLI is configured
if ! aws sts get-caller-identity &> /dev/null; then
    echo "❌ AWS CLI not configured. Please run 'aws configure' first."
    exit 1
fi

# Function to deploy a Lambda
deploy_lambda() {
    local function_name=$1
    local lambda_dir=$2
    
    echo "📦 Deploying $function_name..."
    
    cd "$lambda_dir"
    
    # Create deployment package
    zip -q -r "/tmp/${function_name}.zip" .
    
    # Try to update function code
    if aws lambda get-function --function-name "$function_name" &> /dev/null; then
        aws lambda update-function-code \
            --function-name "$function_name" \
            --zip-file "fileb:///tmp/${function_name}.zip" \
            --no-cli-pager > /dev/null
        echo "  ✓ Updated $function_name"
    else
        echo "  ⚠️  Function $function_name not found. Please create it first via AWS Console or CloudFormation."
    fi
    
    # Cleanup
    rm "/tmp/${function_name}.zip"
    
    cd - > /dev/null
}

# Get the project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Deploy each Lambda function
deploy_lambda "inbound-webhook" "lambdas/inbound-webhook"
deploy_lambda "wa-process" "lambdas/wa-process"
deploy_lambda "wa-send" "lambdas/wa-send"
deploy_lambda "wa-tts" "lambdas/wa-tts"
deploy_lambda "wa-audio-transcribe" "lambdas/wa-audio-transcribe"
deploy_lambda "wa-transcribe-finish" "lambdas/wa-transcribe-finish"
deploy_lambda "wa-image-analyze" "lambdas/wa-image-analyze"
deploy_lambda "wa-image-generate" "lambdas/wa-image-generate"

echo ""
echo "✅ All Lambda functions deployed successfully!"
echo ""
echo "Next steps:"
echo "1. Configure Bedrock Agents (see IMAGE_GENERATION_SETUP.md)"
echo "2. Set up API Gateway webhook"
echo "3. Configure WhatsApp Business API"
echo "4. Test the bot"

