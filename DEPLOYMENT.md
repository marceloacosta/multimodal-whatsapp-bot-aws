# Deployment Guide

This guide walks you through deploying the WhatsApp Multimodal Bot to AWS.

## Prerequisites

- AWS Account with appropriate permissions
- AWS CLI installed and configured
- Python 3.9+ installed
- WhatsApp Business API account (Meta for Developers)
- Access to AWS Bedrock (specifically Claude 3.5 Sonnet and Titan Image Generator)

## Architecture Overview

See `whatsapp_bot_architecture.png` for the complete architecture diagram.

## Deployment Options

### Option 1: Manual Deployment (Recommended for first-time setup)

1. **Set up Bedrock Agents**: Follow `BEDROCK_AGENT_SETUP.md` to create the supervisor and sub-agents
2. **Deploy Lambda Functions**: Use the scripts in `scripts/` directory
3. **Configure API Gateway**: Create REST API with `/webhook` endpoint
4. **Set up Secrets Manager**: Store WhatsApp credentials
5. **Configure WhatsApp Webhook**: Point to your API Gateway URL

### Option 2: Automated Deployment Scripts (Lambdas only)

Use the deployment scripts provided:

```bash
# Deploy all Lambda functions
./scripts/deploy-all-lambdas.sh

# Deploy image generation feature
./deploy-image-generation.sh
```

## AWS Resources Required

### 1. Lambda Functions (8 total)
- `inbound-webhook`: Handles WhatsApp webhooks
- `wa-process`: Main orchestrator
- `wa-send`: Sends messages to WhatsApp
- `wa-tts`: Text-to-Speech conversion
- `wa-audio-transcribe`: Speech-to-Text
- `wa-transcribe-finish`: Transcription callback handler
- `wa-image-analyze`: Image analysis using Claude Vision
- `wa-image-generate`: Image generation using Titan

### 2. API Gateway
- REST API with `/webhook` endpoint
- Methods: GET (verification), POST (receive messages)

### 3. S3 Buckets (2 total)
- Media bucket: Stores incoming media files
- Generated images bucket: Stores AI-generated images

### 4. IAM Roles & Policies
- Lambda execution roles with permissions for:
  - Bedrock (InvokeModel, InvokeAgent)
  - S3 (GetObject, PutObject)
  - Secrets Manager (GetSecretValue)
  - Lambda (InvokeFunction)
  - Transcribe (StartTranscriptionJob)
  - Polly (SynthesizeSpeech)

### 5. Secrets Manager
- WhatsApp API tokens (phone number ID, access token, verify token)

### 6. AWS Bedrock
- **Supervisor Agent**: Main conversational agent
- **ImageCreator Sub-Agent**: Handles image generation requests
- **Foundation Models**:
  - Claude 3.5 Sonnet v2 (for vision and conversation)
  - Claude 3.5 Haiku (for caption generation)
  - Titan Image Generator v2 (for image generation)

## Estimated Costs

- **Lambda**: ~$0.20 per 1M requests + compute time
- **Bedrock**: Pay-per-use (varies by model)
  - Claude 3.5 Sonnet: ~$3 per 1M input tokens
  - Titan Image Generator: ~$0.008 per image
- **S3**: ~$0.023 per GB/month
- **API Gateway**: ~$1 per 1M requests
- **Secrets Manager**: ~$0.40 per secret/month

**Estimated monthly cost for moderate usage (1000 messages/day)**: $20-50

## Post-Deployment Configuration

1. Update API Gateway webhook URL in WhatsApp Business API settings
2. Configure Bedrock Agent instructions (see `supervisor-agent-instructions.txt` and `wa-image-creator-instructions.txt`)
3. Test the webhook with WhatsApp
4. Monitor CloudWatch Logs for any issues

## Security Considerations

- Never commit `.env` file to Git
- Use Secrets Manager for sensitive data
- Enable API Gateway throttling
- Use VPC for Lambda functions (optional, for enhanced security)
- Enable CloudTrail for auditing
- Regular rotate WhatsApp access tokens

## Troubleshooting

See `TROUBLESHOOTING.md` for common issues and solutions.

## Support

For issues or questions, please open an issue on GitHub.

