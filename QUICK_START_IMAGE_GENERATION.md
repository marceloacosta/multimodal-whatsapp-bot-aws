# Quick Start: Image Generation

## TL;DR - Get Started in 5 Minutes

```bash
# 1. Deploy the Lambda functions
./deploy-image-generation.sh

# 2. Enable Bedrock models (AWS Console)
#    Bedrock → Model access → Request access to:
#    - Stable Diffusion XL
#    - Titan Image Generator

# 3. Create the agent (AWS Console)
#    Bedrock → Agents → Create Agent
#    Name: wa-image-creator
#    Model: Claude 3.5 Sonnet
#    Upload schema: lambdas/wa-image-generate/openapi-schema.json

# 4. Test!
#    Send to WhatsApp: "Create an image of a sunset over the ocean"
```

## What You Get

### New Lambda Function: `wa-image-generate`
- Generates images using Stable Diffusion XL or Amazon Titan
- Stores images in S3
- Returns presigned URLs (valid for 1 hour)
- Supports style presets and customization

### Updated Lambda: `wa-send`
- Now supports sending images directly to WhatsApp
- Automatically handles image URLs from generation

### New Agent: `wa-image-creator`
- Specialized sub-agent for image generation
- Called by supervisor agent when user requests images
- Optimizes prompts for better results

## Example Prompts

**Basic:**
- "Create an image of a cat"
- "Generate a sunset"
- "Draw a futuristic city"

**Detailed:**
- "Create a photorealistic image of a white cat with blue eyes sitting on a red cushion, professional photography, studio lighting"
- "Generate a sunset over the ocean in watercolor style with pink and orange clouds"
- "Draw a futuristic city with flying cars, neon lights, cyberpunk style, night scene"

**With Style:**
- "Create an anime style portrait of a young woman"
- "Generate a fantasy landscape in digital-art style"
- "Draw a robot in pixel-art style"

## Architecture

```
User sends: "Create an image of X"
         ↓
Supervisor Agent (detects image generation request)
         ↓
wa-image-creator Agent (optimizes prompt)
         ↓
wa-image-generate Lambda
         ↓
Bedrock Image Model (Stable Diffusion/Titan)
         ↓
S3 (stores image)
         ↓
wa-send Lambda (sends to WhatsApp)
         ↓
User receives image in WhatsApp
```

## Supported Models

### Stable Diffusion XL (Default)
- **Model ID:** `stability.stable-diffusion-xl-v1`
- **Cost:** ~$0.04 per image
- **Time:** 8-12 seconds
- **Best for:** Artistic images, style presets
- **Image size:** 1024x1024

**Style Presets:**
- `photographic` - Realistic photos
- `anime` - Japanese animation style
- `digital-art` - Digital artwork
- `cinematic` - Movie-like scenes
- `comic-book` - Comic book art
- `fantasy-art` - Fantasy illustrations
- `3d-model` - 3D rendered look
- `pixel-art` - Retro pixel art
- And 10+ more!

### Amazon Titan Image Generator
- **Model ID:** `amazon.titan-image-generator-v1`
- **Cost:** ~$0.01 per image
- **Time:** 5-8 seconds
- **Best for:** Photorealistic images
- **Image size:** 1024x1024

**Switch to Titan:**
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

## Customization

### Change Image Size (Stable Diffusion)
Edit `lambdas/wa-image-generate/lambda_function.py`:
```python
body = {
    # ...
    "width": 768,   # Must be multiple of 64
    "height": 1024,
}
```

### Adjust Quality Settings
```python
# Stable Diffusion
"cfg_scale": 7.0,  # 1-35, higher = follow prompt more strictly
"steps": 50,       # 10-150, more steps = higher quality but slower

# Titan
"quality": "premium",  # "standard" or "premium"
"cfgScale": 8.0,       # 1.1-10.0
```

### Change Presigned URL Expiration
Edit `_save_image_to_s3()`:
```python
presigned_url = s3.generate_presigned_url(
    "get_object",
    Params={"Bucket": IMAGE_BUCKET, "Key": key},
    ExpiresIn=7200  # 2 hours instead of 1
)
```

## Cost Breakdown

**Per 100 images:**
- Stable Diffusion XL: $4.00
- Titan Image Generator: $1.00
- Lambda execution: $0.05
- S3 storage (1MB avg): $0.002/month
- S3 transfer: Minimal (presigned URLs)

**Total:** $1-4 per 100 images

## Monitoring

### Watch Logs
```bash
# Image generation logs
aws logs tail /aws/lambda/wa-image-generate --follow

# Filter errors only
aws logs tail /aws/lambda/wa-image-generate --filter-pattern "ERROR"

# Check last 30 minutes
aws logs tail /aws/lambda/wa-image-generate --since 30m
```

### Key Log Events
- `SDXL_REQUEST` or `TITAN_REQUEST` - Generation started
- `IMAGE_SAVED` - Image stored in S3
- `IMAGE_GENERATED` - Success with S3 key
- `BEDROCK_ERROR` - Model invocation failed
- `S3_DOWNLOAD_FAILED` - S3 access issue

### CloudWatch Metrics
- Lambda invocations
- Duration (typically 8-15 seconds)
- Errors
- Throttles

## Troubleshooting

### "Model access denied"
**Fix:** Enable model access in Bedrock Console
```
AWS Console → Bedrock → Model access → Request access
```

### "Insufficient permissions"
**Fix:** Check IAM role has `bedrock:InvokeModel`
```bash
aws iam get-role-policy \
  --role-name wa-image-generate-role \
  --policy-name ImageGenerationPermissions
```

### "Image generation timeout"
**Fix:** Increase Lambda timeout
```bash
aws lambda update-function-configuration \
  --function-name wa-image-generate \
  --timeout 120
```

### Poor image quality
**Fixes:**
1. Make prompt more detailed and specific
2. Try different style presets
3. Increase steps (Stable Diffusion) or use premium quality (Titan)
4. Switch between models

### Images not sending to WhatsApp
**Check:**
1. Presigned URL is valid (not expired)
2. wa-send Lambda has image support (check recent deployment)
3. Image URL is HTTPS (required by WhatsApp)
4. WhatsApp accepts the image format (PNG works)

## Advanced Features

### Add Negative Prompts (Titan only)
```python
# In wa-image-generate request
{
  "prompt": "A beautiful landscape",
  "negativePrompt": "blurry, low quality, distorted, ugly"
}
```

### Batch Generation
Modify Lambda to generate multiple images:
```python
body = {
    # ...
    "samples": 3  # Generate 3 variations
}
```

### Content Filtering
Add prompt validation:
```python
BLOCKED_TERMS = ["violence", "explicit", "inappropriate"]

def validate_prompt(prompt: str) -> bool:
    lower_prompt = prompt.lower()
    return not any(term in lower_prompt for term in BLOCKED_TERMS)
```

### User Galleries
Track user images:
```python
def list_user_images(user_id: str) -> list:
    """List all images generated by a user."""
    prefix = f"{IMAGE_PREFIX}{user_id}/"
    response = s3.list_objects_v2(
        Bucket=IMAGE_BUCKET,
        Prefix=prefix
    )
    return [obj['Key'] for obj in response.get('Contents', [])]
```

## Security Best Practices

1. **Content Moderation:** Implement prompt filtering
2. **Rate Limiting:** Add per-user limits
3. **URL Expiration:** Keep presigned URLs short-lived
4. **Access Control:** Use S3 bucket policies
5. **Audit Logging:** Track all generations

## Next Steps

1. **Add More Styles:** Create custom style presets
2. **Implement Editing:** Use Titan's inpainting feature
3. **Add Variations:** Generate multiple versions
4. **Build Gallery:** Let users browse their creations
5. **Add Feedback:** Collect quality ratings

## Support

For detailed setup: See `IMAGE_GENERATION_SETUP.md`
For issues: Check CloudWatch logs
For costs: Monitor AWS Cost Explorer

## Examples Gallery

Test these prompts:

1. **Nature:** "A misty forest at dawn with sunbeams filtering through ancient trees, photographic style"

2. **Architecture:** "A futuristic glass skyscraper in a cyberpunk city, neon lights, night scene, cinematic"

3. **Characters:** "A friendly robot assistant in a modern home, digital-art style, soft lighting"

4. **Abstract:** "Abstract swirling colors representing joy and creativity, vibrant, digital-art"

5. **Food:** "A gourmet chocolate cake with strawberries, professional food photography, studio lighting"

Happy generating! 🎨

