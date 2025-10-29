# AWS Bedrock Agent Setup Guide

Complete guide for creating and configuring the Bedrock Agents for this WhatsApp bot.

## Overview

This project uses a multi-agent architecture:
- **Supervisor Agent**: Main conversational agent (handles all user interactions)
- **ImageCreator Sub-Agent**: Specialized agent for image generation (called by supervisor)

## Prerequisites

- AWS Account with Bedrock access
- Lambda functions deployed (`wa-process`, `wa-image-analyze`, `wa-image-generate`)
- Bedrock Foundation Model access enabled:
  - Claude 3.5 Sonnet v2
  - Claude 3.5 Haiku
  - Titan Image Generator v2

---

## Part 1: Create the Supervisor Agent

### Step 1: Navigate to Bedrock Console

1. Open AWS Console
2. Go to **Amazon Bedrock** service
3. In the left sidebar, click **Agents**
4. Click **Create Agent** button

### Step 2: Agent Details

**Agent name:** `whatsapp-supervisor-agent` (or your preferred name)

**Description:** 
```
Main WhatsApp bot agent that handles conversations, image analysis, and delegates image generation to sub-agents.
```

**Agent resource role:** Create and use a new service role (default)

**Foundation model:** `Anthropic Claude 3.5 Sonnet v2`

**Enable user input:** ✅ Checked

Click **Next**

### Step 3: Instructions

Copy and paste the instructions from `supervisor-agent-instructions.txt`:

```
You are a helpful WhatsApp assistant that can help with various tasks including image analysis and image generation.

## General Guidelines

- Spanish first if user writes/speaks Spanish; otherwise match user language
- Keep answers concise for messaging
- If you don't know, say so; don't invent

## Audio/Voice Replies

If the user explicitly requests an audio or voice reply:
- Do NOT mention audio, sound, reading, or text-to-speech in your answer
- Simply produce a normal text reply — the backend system will automatically convert it to audio
- Never write meta comments such as "I'll send you an audio", "Here's the voice version", or "I can speak this aloud"

## Image Analysis

When the user message includes an [IMAGE_CONTEXT] block:

Parse it strictly (no guessing):
- s3Uri: S3 URI of the image (e.g., s3://.../image.jpg)
- question: user's question about the image (may be empty)
- language: language code (e.g., es, en), optional

Call the analyzeImage action with:
{
  "s3Uri": "<parsed s3Uri>",
  "question": "<parsed question or empty string>",
  "language": "<parsed language or user language code>"
}

Use only the tool's answer as your final reply.

If s3Uri is missing/invalid, ask the user to resend the image.
If there is no [IMAGE_CONTEXT] block, answer normally (text). Do not call the image tool.

## Image Generation

When the user requests an image:

1. Delegate to the ImageCreator collaborator agent
2. ImageCreator will handle everything (generation, caption, sending)
3. When ImageCreator responds with "✅", respond ONLY with: "✅"

Do NOT add any commentary. The image has already been sent to the user.

If ImageCreator reports an error, explain it briefly to the user.
```

Click **Next**

### Step 4: Add Action Groups

#### Action Group 1: Image Analysis

**Action group name:** `analyzeImage`

**Action group type:** Define with function details

**Action group invocation:**
- Select **AWS Lambda function**
- Choose: `wa-image-analyze`

**Action group function:**
- Function name: `analyzeImage`
- Description: `Analyzes an image using Claude Vision and answers questions about it`

**Parameters:**
1. Parameter 1:
   - Name: `s3Uri`
   - Description: `S3 URI of the image to analyze`
   - Type: `string`
   - Required: ✅

2. Parameter 2:
   - Name: `question`
   - Description: `Question about the image (optional)`
   - Type: `string`
   - Required: ❌

3. Parameter 3:
   - Name: `language`
   - Description: `Language code (es, en, etc)`
   - Type: `string`
   - Required: ❌

Click **Create** and **Next**

### Step 5: Knowledge Bases (Optional)

Skip this step - click **Next**

### Step 6: Review and Create

Review all settings and click **Create Agent**

### Step 7: Prepare the Agent

After creation:
1. Click **Prepare** button (orange button in top right)
2. Wait for preparation to complete (~30 seconds)
3. Note down your **Agent ID** and **Agent Alias ID** (you'll need these for environment variables)

---

## Part 2: Create the ImageCreator Sub-Agent

### Step 1: Create New Agent

1. In Bedrock Console, click **Create Agent**

**Agent name:** `wa-image-creator`

**Description:**
```
Specialized sub-agent for generating AI images using Amazon Titan Image Generator.
```

**Foundation model:** `Anthropic Claude 3.5 Sonnet v2`

Click **Next**

### Step 2: Instructions

Copy instructions from `wa-image-creator-instructions.txt`:

```
You are an expert at generating images from text descriptions.

When a user requests an image:

1. Analyze their request and create a detailed, optimized prompt for the image generation model
2. Use the generateImage tool to create the image
3. When the tool succeeds, respond ONLY with: "✅"

The tool automatically:
- Generates the image
- Creates a natural caption using AI
- Sends the image to the user via WhatsApp

Your only job is to call the tool and respond with "✅" when successful.

If generation fails, explain the error briefly.
```

Click **Next**

### Step 3: Add Action Group (Image Generation)

**Action group name:** `ImageGeneration`

**Action group type:** Define with API schemas

**Action group invocation:**
- Select **AWS Lambda function**
- Choose: `wa-image-generate`

**API Schema:**
- Select **Define via in-line schema editor**
- Copy and paste the contents of `lambdas/wa-image-generate/openapi-schema.json`

Click **Create** and **Next**

### Step 4: Prepare the Sub-Agent

1. Click **Prepare**
2. Wait for completion
3. Create an **Alias**:
   - Name: `dev`
   - Description: `Development version`
   - Point to: **Latest** or **Version 1**

Note down the **Sub-Agent ID** and **Alias ID**

---

## Part 3: Link Sub-Agent to Supervisor

### Step 1: Add Collaborator to Supervisor Agent

1. Go back to your **Supervisor Agent**
2. Click **Edit**
3. Scroll to **Agents** section
4. Click **Add agent collaborator**

### Step 2: Configure Collaborator

**Collaborator name:** `ImageCreator`

**Collaborator instructions:**
```
Use this agent when the user requests to create, generate, or draw an image.
Examples:
- "Create an image of a sunset"
- "Generate a picture of a cat"
- "Draw a mountain landscape"

Delegate the entire request to this agent and return its response.
```

**Agent:**
- Select: `wa-image-creator`
- Alias: `dev` (or the alias you created)

**Association type:** `Supervisor routes to one or more sub-agents`

Click **Save**

### Step 3: Prepare Updated Supervisor

1. Click **Prepare** again
2. Wait for completion
3. Go to **Aliases** tab
4. Edit your existing alias OR create new one:
   - Name: `prod` or `dev`
   - Version: Select the **latest prepared version**

---

## Part 4: Configure Lambda Functions

### Update `wa-process` Lambda

Add these environment variables:

```bash
BEDROCK_AGENT_ID=YOUR_SUPERVISOR_AGENT_ID
BEDROCK_AGENT_ALIAS_ID=YOUR_SUPERVISOR_ALIAS_ID
BEDROCK_REGION=us-east-1
```

### Grant Lambda Permission to Invoke Agent

The Lambda execution role for `wa-process` needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeAgent"
      ],
      "Resource": [
        "arn:aws:bedrock:REGION:ACCOUNT_ID:agent-alias/AGENT_ID/ALIAS_ID"
      ]
    }
  ]
}
```

---

## Part 5: Grant Bedrock Agent Permissions

### Allow Supervisor to Invoke wa-image-analyze

```bash
aws lambda add-permission \
  --function-name wa-image-analyze \
  --statement-id AllowBedrockSupervisorAgent \
  --action lambda:InvokeFunction \
  --principal bedrock.amazonaws.com \
  --source-arn arn:aws:bedrock:REGION:ACCOUNT_ID:agent/SUPERVISOR_AGENT_ID
```

### Allow ImageCreator to Invoke wa-image-generate

```bash
aws lambda add-permission \
  --function-name wa-image-generate \
  --statement-id AllowBedrockImageCreatorAgent \
  --action lambda:InvokeFunction \
  --principal bedrock.amazonaws.com \
  --source-arn arn:aws:bedrock:REGION:ACCOUNT_ID:agent/IMAGE_CREATOR_AGENT_ID
```

---

## Testing

### Test Supervisor Agent

In Bedrock Console:
1. Open your Supervisor Agent
2. Click **Test** tab (right panel)
3. Try: `"Hello, how are you?"`
4. Expected: Natural conversation response

### Test Image Analysis

1. Upload an image to your media S3 bucket
2. In agent test panel, send:
```
[IMAGE_CONTEXT]
s3Uri: s3://your-bucket/path/to/image.jpg
question: What's in this image?
language: en
```
3. Expected: Detailed image description

### Test Image Generation

1. In agent test panel, send: `"Create an image of a sunset over mountains"`
2. Expected: Agent responds with "✅"
3. Check CloudWatch Logs for `wa-image-generate` to verify image was created

---

## Troubleshooting

### Agent Returns "I cannot help with that"

**Cause:** Permissions issue or Lambda not connected

**Fix:**
1. Verify Lambda resource policy allows Bedrock to invoke it
2. Check agent action group configuration
3. Ensure agent is **Prepared** after changes

### Sub-Agent Not Being Called

**Cause:** Supervisor doesn't recognize when to delegate

**Fix:**
1. Check collaborator instructions are clear
2. Verify sub-agent alias is correct
3. Prepare supervisor agent again

### Image Generation Fails

**Cause:** Missing model access or IAM permissions

**Fix:**
1. Enable Bedrock model access (Titan Image Generator v2)
2. Check `wa-image-generate` IAM role has `bedrock:InvokeModel`
3. Verify environment variables are set correctly

---

## Updating Agent Instructions

When you modify instructions:

1. Edit the agent
2. Update instructions
3. Click **Save**
4. **Important:** Click **Prepare** 
5. Go to **Aliases** tab
6. Edit your alias to point to the **new version**
7. Test the changes

**Without updating the alias, changes won't take effect!**

---

## Summary

You should now have:

- ✅ Supervisor Agent created and configured
- ✅ ImageCreator Sub-Agent created
- ✅ Sub-agent linked to supervisor as collaborator
- ✅ Lambda functions connected via action groups
- ✅ Permissions configured
- ✅ Environment variables set

**Next:** Configure API Gateway webhook and test with WhatsApp!

For detailed environment setup, see `DEPLOYMENT.md`.

