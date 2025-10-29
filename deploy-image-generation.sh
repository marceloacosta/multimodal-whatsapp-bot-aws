#!/bin/bash
set -e

# Configuration - UPDATE THESE VALUES WITH YOUR OWN
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID="YOUR_AWS_ACCOUNT_ID"  # ⚠️ REQUIRED: Update with your AWS account ID
LAMBDA_ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/service-role/wa-image-generate-role"
IMAGE_BUCKET="YOUR_MEDIA_BUCKET_NAME"  # ⚠️ REQUIRED: Update with your S3 bucket name
SUPERVISOR_AGENT_ID="YOUR_AGENT_ID"  # Optional: Your Bedrock supervisor agent ID

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Image Generation Setup Script${NC}"
echo -e "${GREEN}========================================${NC}\n"

# Validation: Check if user has updated config
if [[ "$AWS_ACCOUNT_ID" == "YOUR_AWS_ACCOUNT_ID" ]] || [[ "$IMAGE_BUCKET" == "YOUR_MEDIA_BUCKET_NAME" ]]; then
    echo -e "${RED}ERROR: Please update the configuration variables at the top of this script!${NC}"
    echo "You need to set:"
    echo "  - AWS_ACCOUNT_ID (your AWS account ID)"
    echo "  - IMAGE_BUCKET (your S3 bucket name)"
    echo ""
    exit 1
fi

# Step 1: Create IAM Role for Lambda
echo -e "${YELLOW}Step 1: Creating IAM role for wa-image-generate Lambda...${NC}"

# Check if role exists
if aws iam get-role --role-name wa-image-generate-role 2>/dev/null; then
    echo -e "${GREEN}✓ Role already exists${NC}"
else
    echo "Creating role..."
    
    # Trust policy
    cat > /tmp/lambda-trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

    aws iam create-role \
        --role-name wa-image-generate-role \
        --assume-role-policy-document file:///tmp/lambda-trust-policy.json \
        --description "Role for image generation Lambda"
    
    # Attach basic execution role
    aws iam attach-role-policy \
        --role-name wa-image-generate-role \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    
    # Create and attach custom policy
    cat > /tmp/image-gen-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInvoke",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel"],
      "Resource": [
        "arn:aws:bedrock:${AWS_REGION}::foundation-model/amazon.titan-image-generator-v2:0",
        "arn:aws:bedrock:${AWS_REGION}::foundation-model/us.anthropic.claude-3-5-haiku-20241022-v1:0"
      ]
    },
    {
      "Sid": "S3ImageAccess",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::${IMAGE_BUCKET}/generated-images/*"
    },
    {
      "Sid": "LambdaInvoke",
      "Effect": "Allow",
      "Action": ["lambda:InvokeFunction"],
      "Resource": "arn:aws:lambda:${AWS_REGION}:${AWS_ACCOUNT_ID}:function:wa-send"
    }
  ]
}
EOF

    aws iam put-role-policy \
        --role-name wa-image-generate-role \
        --policy-name ImageGenerationPermissions \
        --policy-document file:///tmp/image-gen-policy.json
    
    echo -e "${GREEN}✓ Role created${NC}"
    echo "Waiting 10 seconds for IAM propagation..."
    sleep 10
fi

LAMBDA_ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/wa-image-generate-role"

# Step 2: Deploy wa-image-generate Lambda
echo -e "\n${YELLOW}Step 2: Deploying wa-image-generate Lambda...${NC}"

cd lambdas/wa-image-generate
zip -q -r /tmp/wa-image-generate.zip lambda_function.py
cd ../..

# Check if function exists
if aws lambda get-function --function-name wa-image-generate 2>/dev/null; then
    echo "Updating existing function..."
    aws lambda update-function-code \
        --function-name wa-image-generate \
        --zip-file fileb:///tmp/wa-image-generate.zip \
        --no-cli-pager > /dev/null
    
    aws lambda update-function-configuration \
        --function-name wa-image-generate \
        --timeout 90 \
        --memory-size 512 \
        --environment Variables="{
            BEDROCK_REGION=${AWS_REGION},
            IMAGE_BUCKET=${IMAGE_BUCKET},
            IMAGE_PREFIX=generated-images/,
            IMAGE_MODEL_ID=amazon.titan-image-generator-v2:0,
            WA_SEND_FUNCTION=wa-send
        }" \
        --no-cli-pager > /dev/null
else
    echo "Creating new function..."
    aws lambda create-function \
        --function-name wa-image-generate \
        --runtime python3.13 \
        --role ${LAMBDA_ROLE_ARN} \
        --handler lambda_function.lambda_handler \
        --zip-file fileb:///tmp/wa-image-generate.zip \
        --timeout 90 \
        --memory-size 512 \
        --environment Variables="{
            BEDROCK_REGION=${AWS_REGION},
            IMAGE_BUCKET=${IMAGE_BUCKET},
            IMAGE_PREFIX=generated-images/,
            IMAGE_MODEL_ID=amazon.titan-image-generator-v2:0,
            WA_SEND_FUNCTION=wa-send
        }" \
        --no-cli-pager > /dev/null
fi

echo -e "${GREEN}✓ Lambda deployed${NC}"

# Step 3: Update wa-send Lambda
echo -e "\n${YELLOW}Step 3: Updating wa-send Lambda to support images...${NC}"

cd lambdas/wa-send
zip -q -r /tmp/wa-send.zip lambda_function.py
cd ../..

aws lambda update-function-code \
    --function-name wa-send \
    --zip-file fileb:///tmp/wa-send.zip \
    --no-cli-pager > /dev/null

echo -e "${GREEN}✓ wa-send updated${NC}"

# Step 4: Wait for functions to be ready
echo -e "\n${YELLOW}Step 4: Waiting for Lambda functions to be active...${NC}"
sleep 5

# Step 5: Test wa-image-generate
echo -e "\n${YELLOW}Step 5: Testing wa-image-generate Lambda...${NC}"

cat > /tmp/test-image-gen.json << 'EOF'
{
  "body": "{\"prompt\":\"A serene mountain landscape at sunset with purple clouds, oil painting style\",\"userId\":\"test-user\",\"style\":\"photographic\"}"
}
EOF

echo "Invoking test..."
aws lambda invoke \
    --function-name wa-image-generate \
    --payload file:///tmp/test-image-gen.json \
    --no-cli-pager \
    /tmp/test-response.json > /dev/null 2>&1

if grep -q '"success":true' /tmp/test-response.json 2>/dev/null; then
    echo -e "${GREEN}✓ Test successful!${NC}"
    echo "Generated image URL:"
    cat /tmp/test-response.json | jq -r '.body' | jq -r '.image_url' 2>/dev/null || echo "  (check /tmp/test-response.json for details)"
else
    echo -e "${RED}✗ Test failed. Check /tmp/test-response.json for details${NC}"
    cat /tmp/test-response.json
fi

# Summary
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}\n"

echo "Next steps:"
echo "1. Enable Bedrock model access in AWS Console:"
echo "   - Go to Bedrock → Model access"
echo "   - Request access to:"
echo "     • Amazon Titan Image Generator v2"
echo "     • Claude 3.5 Haiku (for caption generation)"
echo ""
echo "2. Create the Image Generation Sub-Agent:"
echo "   - Follow the guide in IMAGE_GENERATION_SETUP.md"
echo "   - Create agent 'wa-image-creator'"
echo "   - Copy instructions from wa-image-creator-instructions.txt"
echo "   - Add action group with OpenAPI schema from lambdas/wa-image-generate/openapi-schema.json"
echo ""
echo "3. Configure Supervisor Agent:"
echo "   - Add wa-image-creator as a sub-agent collaborator"
echo "   - Update instructions from supervisor-agent-instructions.txt"
echo ""
echo "4. Test via WhatsApp:"
echo "   Send: 'Create an image of a sunset over mountains'"
echo ""
echo -e "${YELLOW}View Logs:${NC}"
echo "  aws logs tail /aws/lambda/wa-image-generate --follow"
echo ""

# Cleanup temp files
rm -f /tmp/lambda-trust-policy.json /tmp/image-gen-policy.json /tmp/wa-image-generate.zip /tmp/wa-send.zip

