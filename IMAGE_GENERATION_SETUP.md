# Image Generation Agent Setup Guide

This guide will help you set up a new Bedrock Agent for image generation that will be called by your supervisor agent.

## Architecture Overview

```
WhatsApp User
    ↓
Supervisor Agent (existing)
    ↓ (calls sub-agent when needed)
Image Generation Agent (new)
    ↓
wa-image-generate Lambda
    ↓
Bedrock Image Models (Stable Diffusion XL or Titan)
    ↓
S3 (stores generated images)
    ↓
Returns presigned URL to user
```

## Step 1: Create the Lambda Function

### 1.1 Deploy the Lambda

```bash
cd lambdas/wa-image-generate
zip -r function.zip lambda_function.py

aws lambda create-function \
  --function-name wa-image-generate \
  --runtime python3.13 \
  --role arn:aws:iam::YOUR_ACCOUNT:role/YOUR_LAMBDA_ROLE \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://function.zip \
  --timeout 60 \
  --memory-size 512 \
  --environment Variables='{
    BEDROCK_REGION=us-east-1,
    IMAGE_BUCKET=your-media-bucket,
    IMAGE_PREFIX=generated-images/,
    IMAGE_MODEL_ID=stability.stable-diffusion-xl-v1
  }'
```

### 1.2 Create IAM Role for the Lambda

The Lambda needs these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInvoke",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/stability.stable-diffusion-xl-v1",
        "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-image-generator-v1"
      ]
    },
    {
      "Sid": "S3WriteImages",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:PutObjectAcl"
      ],
      "Resource": "arn:aws:s3:::your-media-bucket/generated-images/*"
    },
    {
      "Sid": "S3GeneratePresignedUrls",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::your-media-bucket/generated-images/*"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

### 1.3 Enable Model Access in Bedrock

Before using the models, enable them in Bedrock Console:

1. Go to AWS Console → Bedrock → Model access
2. Request access to:
   - **Stable Diffusion XL** (stability.stable-diffusion-xl-v1)
   - **Titan Image Generator** (amazon.titan-image-generator-v1)
3. Wait for approval (usually instant)

## Step 2: Create the Image Generation Agent

### 2.1 Create Agent via Console

1. Go to **AWS Console → Bedrock → Agents**
2. Click **Create Agent**
3. Configure:
   - **Name**: `wa-image-creator`
   - **Description**: `Agent specialized in generating images and illustrations based on text descriptions`
   - **Model**: Choose `Claude 3.5 Sonnet` or `Claude 3 Haiku`
   - **Instructions**:
   ```
   You are an expert at generating images and illustrations. When a user requests an image:
   
   1. Analyze their request and create a detailed, optimized prompt for the image generation model
   2. Consider artistic style, composition, colors, mood, and technical details
   3. Use the generateImage tool to create the image
   4. Return the image URL to the user with a brief description
   
   Best practices for prompts:
   - Be specific and detailed
   - Include style references (e.g., "photorealistic", "watercolor", "anime")
   - Specify composition (e.g., "close-up", "wide angle", "bird's eye view")
   - Mention lighting and mood
   - Include relevant details about subjects, colors, and background
   
   If the user's request is vague, ask clarifying questions about:
   - Subject matter
   - Desired style or artistic approach
   - Color preferences
   - Mood or atmosphere
   - Intended use of the image
   ```

### 2.2 Add Action Group

1. In the agent configuration, click **Add Action Group**
2. Configure:
   - **Name**: `ImageGenerationTools`
   - **Description**: `Tools for generating AI images`
   - **Action group type**: Define with API schemas
   - **Action group invocation**: Lambda function
   - **Lambda function**: Select `wa-image-generate`
3. Upload the OpenAPI schema from `lambdas/wa-image-generate/openapi-schema.json`
4. **Save**

### 2.3 Grant Lambda Invoke Permission

Allow the agent to invoke the Lambda:

```bash
aws lambda add-permission \
  --function-name wa-image-generate \
  --statement-id bedrock-agent-invoke \
  --action lambda:InvokeFunction \
  --principal bedrock.amazonaws.com \
  --source-arn arn:aws:bedrock:us-east-1:YOUR_ACCOUNT:agent/AGENT_ID
```

### 2.4 Create Agent Alias

1. Click **Create Alias**
2. Name: `production` or `v1`
3. Wait for alias creation

## Step 3: Configure Supervisor Agent to Call Sub-Agent

### 3.1 Update Supervisor Agent Instructions

Add to your supervisor agent's instructions:

```
# Image Generation Capability

When a user asks you to create, generate, or draw an image or illustration, 
you should invoke the wa-image-creator sub-agent by using the appropriate tool.

Examples of requests that require image generation:
- "Create an image of a sunset"
- "Draw a cat playing piano"
- "Generate an illustration of a futuristic city"
- "Make me a picture of..."
- "Can you create/draw/generate/make..."

The sub-agent will handle the actual image generation and return a URL to the image.
```

### 3.2 Add Sub-Agent as Action Group (Console Method)

**Option A: Using Agent Collaboration (Recommended)**

1. Go to your supervisor agent (`whatsapp-demo-supervisor`)
2. Scroll to **Agent Collaboration**
3. Click **Associate agents**
4. Select `wa-image-creator`
5. Save and prepare a new version

**Option B: Manual API Call Method**

If agent collaboration is not available, you can call the image generation agent via Lambda:

Create a bridge Lambda or update your orchestrator to:

```python
def _invoke_image_generation_agent(session_id: str, prompt: str) -> dict:
    """Call the image generation sub-agent."""
    bedrock_agent = boto3.client("bedrock-agent-runtime")
    
    response = bedrock_agent.invoke_agent(
        agentId="IMAGE_AGENT_ID",
        agentAliasId="IMAGE_AGENT_ALIAS_ID",
        sessionId=session_id,
        inputText=prompt,
        enableTrace=True
    )
    
    # Parse streaming response
    final_text = ""
    for event in response.get("completion", []):
        if "chunk" in event:
            chunk_bytes = event["chunk"].get("bytes")
            if chunk_bytes:
                final_text += chunk_bytes.decode("utf-8")
    
    return {"response": final_text}
```

## Step 4: Test the Image Generation

### Test Directly via Lambda

```bash
aws lambda invoke \
  --function-name wa-image-generate \
  --payload '{
    "body": "{\"prompt\":\"A serene mountain landscape at sunset with purple clouds, oil painting style\",\"userId\":\"test-user\",\"style\":\"photographic\"}"
  }' \
  /tmp/image-response.json

cat /tmp/image-response.json | jq .
```

### Test via WhatsApp

Send messages like:
- "Create an image of a cat wearing a space suit"
- "Generate a sunset over the ocean in watercolor style"
- "Draw a futuristic city with flying cars"
- "Make me a cartoon illustration of a happy robot"

### Monitor Logs

```bash
# Watch image generation logs
aws logs tail /aws/lambda/wa-image-generate --follow

# Check specific errors
aws logs tail /aws/lambda/wa-image-generate --since 10m --filter-pattern "ERROR"
```

## Step 5: Integrate with WhatsApp Flow

### Option 1: Direct URL Response

The agent returns the presigned URL directly to the user as text. User clicks link to view.

### Option 2: Send Image via WhatsApp API (Recommended)

Update `wa-send` Lambda to support sending images:

```python
def send_image_link(to_e164: str, image_url: str, caption: str = None):
    """Send an image to WhatsApp using a presigned URL."""
    url = f"{GRAPH_BASE}/{PHONE_NUMBER_ID}/messages"
    body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_e164,
        "type": "image",
        "image": {
            "link": image_url,
            "caption": caption
        }
    }
    return _post(url, body)
```

Then update `wa-process` to detect image generation responses and send via WhatsApp:

```python
# In wa-process after agent response
if "image_url" in agent_reply or "generated image" in agent_reply.lower():
    # Extract URL from response
    import re
    url_match = re.search(r'https://[^\s]+', agent_reply)
    if url_match:
        image_url = url_match.group(0)
        # Send image instead of text
        payload = {
            "to": from_id,
            "image_url": image_url,
            "caption": "Here's your generated image!"
        }
        _lambda.invoke(
            FunctionName=WA_SEND_FUNCTION,
            InvocationType="Event",
            Payload=json.dumps(payload).encode("utf-8")
        )
        return
```

## Model Options

### Stable Diffusion XL (Default)
- **Model ID**: `stability.stable-diffusion-xl-v1`
- **Pros**: High quality, supports style presets, good for artistic images
- **Image size**: 1024x1024 (configurable)
- **Cost**: ~$0.04 per image

### Amazon Titan Image Generator
- **Model ID**: `amazon.titan-image-generator-v1`
- **Pros**: Fast, supports negative prompts, good for photorealistic images
- **Image size**: 1024x1024, 768x768, etc.
- **Cost**: ~$0.01 per image

To switch models, update the Lambda environment variable:
```bash
aws lambda update-function-configuration \
  --function-name wa-image-generate \
  --environment Variables='{
    BEDROCK_REGION=us-east-1,
    IMAGE_BUCKET=your-media-bucket,
    IMAGE_PREFIX=generated-images/,
    IMAGE_MODEL_ID=amazon.titan-image-generator-v1
  }'
```

## Troubleshooting

### "Model access denied"
- Ensure you've requested access in Bedrock Console → Model access

### "Insufficient permissions"
- Check Lambda IAM role has `bedrock:InvokeModel` for the specific model ARN
- Check Lambda can write to S3 bucket

### "Invalid style preset"
- Style presets only work with Stable Diffusion, not Titan
- Use valid style names from the enum

### Image quality issues
- Make prompts more detailed and specific
- Try different style presets
- Adjust cfg_scale for prompt adherence
- Switch between Stable Diffusion and Titan

### Large response times
- Image generation takes 5-15 seconds typically
- Consider adding a "processing" message to user
- Increase Lambda timeout to 60-90 seconds

## Cost Estimation

**Per 1000 images generated:**
- Stable Diffusion XL: ~$40
- Titan Image Generator: ~$10
- Lambda execution: ~$0.50
- S3 storage (1 MB avg per image): ~$0.02/month
- S3 transfer (presigned URLs): Variable

**Total per 1000 images**: $10-40 + Lambda/S3 costs

## Next Steps

1. Add image size customization
2. Support image editing (Titan supports inpainting/outpainting)
3. Add image variation generation
4. Implement content moderation filters
5. Add user galleries (list previously generated images)
6. Support batch generation

## Security Considerations

- Presigned URLs expire after 1 hour (configurable)
- Add content filtering to prevent inappropriate prompts
- Consider adding watermarks to generated images
- Implement rate limiting per user
- Store generation metadata for auditing

