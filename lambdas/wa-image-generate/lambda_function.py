import os
import json
import logging
import time
import uuid
import base64
from typing import Dict, Any, Optional

import boto3
from botocore.exceptions import ClientError

LOG = logging.getLogger()
LOG.setLevel(logging.INFO)

BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")
IMAGE_BUCKET = os.environ.get("IMAGE_BUCKET")  # REQUIRED: Set in Lambda environment variables
if not IMAGE_BUCKET:
    raise ValueError("IMAGE_BUCKET environment variable is required")
IMAGE_PREFIX = os.environ.get("IMAGE_PREFIX", "generated-images/")
WA_SEND_FUNCTION = os.environ.get("WA_SEND_FUNCTION", "wa-send")

# Image generation model - Stable Diffusion XL or Titan Image Generator
# Options:
#   - stability.stable-diffusion-xl-v1
#   - amazon.titan-image-generator-v1
IMAGE_MODEL_ID = os.environ.get("IMAGE_MODEL_ID", "stability.stable-diffusion-xl-v1")

s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
_lambda = boto3.client("lambda")


def _safe_json(obj: Any, max_len: int = 1200) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    if len(s) > max_len:
        s = s[:max_len] + f"... [truncated {len(s) - max_len} chars]"
    return s


def _generate_with_stable_diffusion(prompt: str, style_preset: Optional[str] = None) -> bytes:
    """
    Generate an image using Stable Diffusion XL.
    Returns image bytes (PNG format).
    """
    body = {
        "text_prompts": [
            {
                "text": prompt,
                "weight": 1.0
            }
        ],
        "cfg_scale": 7.0,  # How strictly to follow the prompt (1-35)
        "steps": 50,       # Number of diffusion steps (10-150)
        "seed": 0,         # Random seed (0 = random)
        "width": 1024,     # Must be multiple of 64
        "height": 1024,
    }
    
    if style_preset:
        # Available styles: 3d-model, analog-film, anime, cinematic, comic-book,
        # digital-art, enhance, fantasy-art, isometric, line-art, low-poly,
        # modeling-compound, neon-punk, origami, photographic, pixel-art, tile-texture
        body["style_preset"] = style_preset

    LOG.info("SDXL_REQUEST %s", _safe_json({
        "model": IMAGE_MODEL_ID,
        "prompt": prompt[:200],
        "style": style_preset
    }))

    try:
        response = bedrock.invoke_model(
            modelId=IMAGE_MODEL_ID,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json"
        )
        
        response_body = json.loads(response["body"].read())
        
        # Stable Diffusion returns base64-encoded images
        artifacts = response_body.get("artifacts", [])
        if not artifacts:
            raise ValueError("No artifacts returned from Stable Diffusion")
        
        image_base64 = artifacts[0].get("base64")
        if not image_base64:
            raise ValueError("No base64 image in artifact")
        
        # Decode base64 to bytes
        image_bytes = base64.b64decode(image_base64)
        return image_bytes
        
    except ClientError as e:
        LOG.error("BEDROCK_ERROR %s", str(e))
        raise


def _generate_with_titan(prompt: str, negative_prompt: Optional[str] = None) -> bytes:
    """
    Generate an image using Amazon Titan Image Generator.
    Returns image bytes (PNG format).
    """
    # Titan has a 512 character limit for prompts
    prompt_text = prompt[:512] if len(prompt) > 512 else prompt
    
    body = {
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {
            "text": prompt_text
        },
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "quality": "premium",  # standard or premium
            "height": 1024,
            "width": 1024,
            "cfgScale": 8.0,       # How closely to follow prompt (1.1-10.0)
            "seed": 0              # 0 = random
        }
    }
    
    if negative_prompt:
        body["textToImageParams"]["negativeText"] = negative_prompt

    LOG.info("TITAN_REQUEST %s", _safe_json({
        "model": IMAGE_MODEL_ID,
        "prompt": prompt[:200]
    }))

    try:
        response = bedrock.invoke_model(
            modelId=IMAGE_MODEL_ID,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json"
        )
        
        response_body = json.loads(response["body"].read())
        
        # Titan returns base64-encoded images
        images = response_body.get("images", [])
        if not images:
            raise ValueError("No images returned from Titan")
        
        image_base64 = images[0]
        image_bytes = base64.b64decode(image_base64)
        return image_bytes
        
    except ClientError as e:
        LOG.error("BEDROCK_ERROR %s", str(e))
        raise


def _save_image_to_s3(image_bytes: bytes, user_id: str, prompt: str) -> Dict[str, str]:
    """
    Save generated image to S3 and return URLs.
    Returns dict with s3_uri, s3_key, and presigned_url.
    """
    ts = int(time.time())
    filename = f"{ts}-{uuid.uuid4().hex}.png"
    key = f"{IMAGE_PREFIX}{user_id}/{filename}"
    
    # Upload to S3
    s3.put_object(
        Bucket=IMAGE_BUCKET,
        Key=key,
        Body=image_bytes,
        ContentType="image/png",
        Metadata={
            "prompt": prompt[:1000],  # Store prompt in metadata
            "generated_at": str(ts)
        }
    )
    
    # Generate presigned URL (valid for 1 hour)
    presigned_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": IMAGE_BUCKET, "Key": key},
        ExpiresIn=3600
    )
    
    s3_uri = f"s3://{IMAGE_BUCKET}/{key}"
    
    LOG.info("IMAGE_SAVED %s", _safe_json({
        "s3_uri": s3_uri,
        "key": key,
        "size_bytes": len(image_bytes)
    }))
    
    return {
        "s3_uri": s3_uri,
        "s3_key": key,
        "presigned_url": presigned_url,
        "size_bytes": len(image_bytes)
    }


def _generate_image_core(
    prompt: str,
    user_id: str,
    style: Optional[str] = None,
    negative_prompt: Optional[str] = None
) -> Dict[str, Any]:
    """
    Core image generation logic.
    Returns dict with image URLs and metadata.
    """
    # Validate prompt
    if not prompt or len(prompt.strip()) < 3:
        raise ValueError("Prompt must be at least 3 characters")
    
    prompt = prompt.strip()
    
    # Generate image based on model type
    if "titan" in IMAGE_MODEL_ID.lower():
        image_bytes = _generate_with_titan(prompt, negative_prompt)
    else:
        # Default to Stable Diffusion
        image_bytes = _generate_with_stable_diffusion(prompt, style)
    
    # Save to S3
    save_result = _save_image_to_s3(image_bytes, user_id, prompt)
    
    return {
        "success": True,
        "prompt": prompt,
        "model": IMAGE_MODEL_ID,
        "s3_uri": save_result["s3_uri"],
        "s3_key": save_result["s3_key"],
        "image_url": save_result["presigned_url"],
        "size_bytes": save_result["size_bytes"],
        "format": "png"
    }


def _create_caption(original_user_text: str, prompt: str) -> str:
    """
    Creates a natural, conversational caption using an LLM based on the user's original request.
    """
    if not original_user_text or len(original_user_text.strip()) == 0:
        return "¡Aquí está tu imagen! 🎨"
    
    try:
        # Use Bedrock to generate a natural caption
        caption_prompt = f"""Generate a short, friendly caption for an image that was just created.

User's original request: "{original_user_text}"

Rules:
- Write in the SAME language as the user's request
- Max 80 characters
- Be conversational and friendly
- Use 1-2 emojis maximum
- Don't describe the image, just acknowledge it's ready
- Ask if they like it or say you hope they like it

Examples:
- "¡Aquí está tu gato! ¿Te gusta? 😊"
- "Here's your rabbit! Hope you like it 🐰"
- "¡Tu atardecer está listo! ✨"

Caption:"""

        resp = bedrock.converse(
            modelId="us.anthropic.claude-3-5-haiku-20241022-v1:0",
            messages=[{
                "role": "user",
                "content": [{"text": caption_prompt}]
            }],
            inferenceConfig={
                "temperature": 0.7,
                "maxTokens": 100
            }
        )
        
        caption = resp["output"]["message"]["content"][0]["text"].strip()
        # Remove quotes if present
        caption = caption.strip('"\'')
        
        LOG.info("LLM_CAPTION_GENERATED %s", _safe_json({"original": original_user_text[:50], "caption": caption}, 300))
        
        return caption[:1024]
        
    except Exception as e:
        LOG.error("CAPTION_GENERATION_FAILED %s", str(e))
        # Fallback to simple caption
        return "¡Aquí está tu imagen! 🎨"


def _ok_agent_response(action_group: str, api_path: str, http_method: str, body_obj: dict) -> dict:
    """Build successful Bedrock Agent response."""
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "apiPath": api_path,
            "httpMethod": http_method,
            "httpStatusCode": 200,
            "responseBody": {
                "application/json": {"body": json.dumps(body_obj, ensure_ascii=False)}
            }
        }
    }


def _error_agent_response(
    action_group: str,
    api_path: str,
    http_method: str,
    status_code: int,
    error_msg: str
) -> dict:
    """Build error Bedrock Agent response."""
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "apiPath": api_path,
            "httpMethod": http_method,
            "httpStatusCode": status_code,
            "responseBody": {
                "application/json": {
                    "body": json.dumps({"error": error_msg}, ensure_ascii=False)
                }
            }
        }
    }


def lambda_handler(event, context):
    """
    Lambda handler for image generation.
    Supports both Bedrock Agent invocation and direct API Gateway calls.
    """
    LOG.info("RAW_EVENT %s", _safe_json({"keys": list((event or {}).keys())}, 400))
    LOG.info("FULL_EVENT %s", _safe_json(event, 2000))
    
    is_agent_tool = isinstance(event, dict) and "actionGroup" in event
    
    try:
        if is_agent_tool:
            # -------- Bedrock Agent Tool Invocation --------
            action_group = event.get("actionGroup") or "ImageGenerationTools"
            api_path = event.get("apiPath") or "/generate-image"
            http_method = event.get("httpMethod") or "POST"
            
            # Extract parameters from requestBody
            prompt = style = negative_prompt = user_id = None
            req_body_raw = event.get("requestBody") or "{}"
            
            LOG.info("REQUEST_BODY_RAW %s", _safe_json({"raw": req_body_raw}, 500))
            
            try:
                body = json.loads(req_body_raw) if isinstance(req_body_raw, str) else req_body_raw
            except Exception as e:
                LOG.error("JSON_PARSE_ERROR %s", str(e))
                body = {}
            
            LOG.info("PARSED_BODY %s", _safe_json(body, 500))
            
            # Handle Bedrock Agent's nested requestBody format
            if isinstance(body, dict) and "content" in body:
                # Format: {"content": {"application/json": {"properties": [...]}}}
                content = body.get("content", {})
                app_json = content.get("application/json", {})
                properties = app_json.get("properties", [])
                
                for prop in properties:
                    if isinstance(prop, dict):
                        name = prop.get("name")
                        val = prop.get("value")
                        if name == "prompt":
                            prompt = val
                        elif name == "style":
                            style = val
                        elif name == "negativePrompt":
                            negative_prompt = val
                        elif name == "userId":
                            user_id = val
            else:
                # Flat format: {"prompt": "...", "userId": "..."}
                prompt = body.get("prompt")
                style = body.get("style")
                negative_prompt = body.get("negativePrompt")
                user_id = body.get("userId", "unknown")
            
            LOG.info("EXTRACTED_PARAMS %s", _safe_json({"prompt": prompt[:100] if prompt else None, "user_id": user_id}, 300))
            
            # Also check parameters list (alternative format)
            if not prompt:
                params = event.get("parameters", [])
                for p in params:
                    if isinstance(p, dict):
                        name = p.get("name")
                        val = p.get("value")
                        if name == "prompt":
                            prompt = val
                        elif name == "style":
                            style = val
                        elif name == "negativePrompt":
                            negative_prompt = val
                        elif name == "userId":
                            user_id = val
            
            # If still no user_id, try to extract from sessionAttributes
            if not user_id or user_id == "unknown":
                session_attrs = event.get("sessionAttributes", {})
                user_phone = session_attrs.get("userPhone")
                if user_phone:
                    user_id = user_phone
                    LOG.info("EXTRACTED_USER_FROM_SESSION_ATTRS %s", _safe_json({"user_id": user_id}, 200))
            
            if not prompt:
                return _error_agent_response(
                    action_group, api_path, http_method, 400,
                    "Missing required parameter: prompt"
                )
            
            # Generate image
            result = _generate_image_core(prompt, user_id, style, negative_prompt)
            
            LOG.info("IMAGE_GENERATED %s", _safe_json({
                "prompt": prompt[:100],
                "s3_key": result["s3_key"],
                "image_url": result["image_url"][:100]
            }))
            
            # Generate caption with LLM and send directly to user
            if user_id and str(user_id).lower() not in ["unknown", "none", "null", ""]:
                session_attrs = event.get("sessionAttributes", {})
                original_text = session_attrs.get("originalUserText", "")
                
                # Create natural caption using LLM
                caption = _create_caption(original_text, prompt)
                
                try:
                    _lambda.invoke(
                        FunctionName=WA_SEND_FUNCTION,
                        InvocationType="Event",
                        Payload=json.dumps({
                            "to": user_id,
                            "image_url": result["image_url"],
                            "caption": caption
                        }).encode("utf-8")
                    )
                    LOG.info("WA_SEND_INVOKED %s", _safe_json({
                        "to": user_id, 
                        "caption": caption[:100], 
                        "image_url": result["image_url"][:100]
                    }, 400))
                    
                    # Return minimal response to force agent to respond with ✅
                    return {
                        "messageVersion": "1.0",
                        "response": {
                            "actionGroup": action_group,
                            "apiPath": api_path,
                            "httpMethod": http_method,
                            "httpStatusCode": 200,
                            "responseBody": {
                                "application/json": {
                                    "body": json.dumps({
                                        "status": "success",
                                        "message": "Image sent to user"
                                    })
                                }
                            }
                        }
                    }
                except Exception as e:
                    LOG.error("WA_SEND_FAILED %s", str(e))
            
            return _ok_agent_response(action_group, api_path, http_method, result)
        
        # -------- Direct API Gateway Invocation --------
        body_raw = event.get("body")
        body = json.loads(body_raw) if isinstance(body_raw, str) else (body_raw or {})
        
        prompt = body.get("prompt")
        style = body.get("style")
        negative_prompt = body.get("negativePrompt")
        user_id = body.get("userId", "unknown")
        
        if not prompt:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing required parameter: prompt"})
            }
        
        result = _generate_image_core(prompt, user_id, style, negative_prompt)
        
        LOG.info("IMAGE_GENERATED %s", _safe_json({
            "prompt": prompt[:100],
            "s3_key": result["s3_key"]
        }))
        
        return {
            "statusCode": 200,
            "body": json.dumps(result, ensure_ascii=False)
        }
    
    except ValueError as e:
        LOG.error("VALIDATION_ERROR %s", str(e))
        if is_agent_tool:
            return _error_agent_response(
                event.get("actionGroup", "ImageGenerationTools"),
                event.get("apiPath", "/generate-image"),
                event.get("httpMethod", "POST"),
                400,
                str(e)
            )
        return {
            "statusCode": 400,
            "body": json.dumps({"error": str(e)})
        }
    
    except Exception as e:
        LOG.error("UNEXPECTED_ERROR %s", str(e))
        if is_agent_tool:
            return _error_agent_response(
                event.get("actionGroup", "ImageGenerationTools"),
                event.get("apiPath", "/generate-image"),
                event.get("httpMethod", "POST"),
                500,
                f"Image generation failed: {str(e)}"
            )
        return {
            "statusCode": 500,
            "body": json.dumps({"error": f"Image generation failed: {str(e)}"})
        }

