import os
import json
import logging
import re
import base64
import boto3

LOG = logging.getLogger()
LOG.setLevel(logging.INFO)

BEDROCK_REGION  = os.environ["BEDROCK_REGION"]
VISION_MODEL_ID = os.environ.get("VISION_MODEL_ID", "us.anthropic.claude-3-5-sonnet-20241022-v2:0")

s3  = boto3.client("s3")
brt = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)

def _safe_json(o, n=1200):
    try:
        s = json.dumps(o, ensure_ascii=False, default=str)
    except Exception:
        s = str(o)
    return s if len(s) <= n else s[:n] + f"...[{len(s)-n} more]"

def _analyze_core(s3_uri: str, question: str | None, language: str | None) -> dict:
    # Validate S3 URI format and parse bucket/key
    if not s3_uri.startswith("s3://"):
        raise ValueError("s3Uri must start with s3://")
    
    # Parse S3 URI to extract bucket and key
    _, rest = s3_uri.split("s3://", 1)
    bucket, key = rest.split("/", 1)
    
    # Download image from S3
    LOG.info("DOWNLOADING_IMAGE %s", _safe_json({"bucket": bucket, "key": key}, 400))
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        image_bytes = obj["Body"].read()
    except Exception as e:
        LOG.error("S3_DOWNLOAD_FAILED %s", str(e))
        raise ValueError(f"Failed to download image from {s3_uri}: {str(e)}")
    
    lang      = (language or "es").strip()
    user_text = (question or (
        "Describe la imagen y cualquier texto relevante." if lang.startswith("es")
        else "Describe the image and any relevant text."
    )).strip()

    system_msg = (
        "You are a careful vision assistant. Analyze the image and answer clearly and concisely. "
        "If something is uncertain, say so. Avoid hallucinations."
    )

    # Determine image format from the S3 key extension
    ext = key.lower().split('.')[-1]
    format_map = {
        'jpg': 'jpeg',
        'jpeg': 'jpeg',
        'png': 'png',
        'gif': 'gif',
        'webp': 'webp'
    }
    img_format = format_map.get(ext, 'jpeg')  # default to jpeg

    resp = brt.converse(
        modelId=VISION_MODEL_ID,
        system=[{"text": system_msg}],
        messages=[{
            "role": "user",
            "content": [
                {"text": user_text},
                {
                    "image": {
                        "format": img_format,
                        "source": {
                            "bytes": image_bytes
                        }
                    }
                }
            ]
        }],
        inferenceConfig={"temperature": 0.1, "maxTokens": 600}
    )

    # Extract text from output - using same pattern as your orchestrator
    out = resp.get("output", {})
    msg = out.get("message") or (out.get("messages") or [{}])[0]
    content = msg.get("content", [])
    text_chunks = [c.get("text") for c in content if isinstance(c, dict) and c.get("text")]
    answer = (text_chunks[0] if text_chunks else "").strip()
    
    if not answer:
        answer = "No pude extraer información útil de la imagen."
    return {"answer": answer}

def _parse_parameters_list(params):
    """Bedrock may pass a list of {name, value} instead of requestBody."""
    if not isinstance(params, list):
        return {}
    out = {}
    for p in params:
        if isinstance(p, dict):
            name = p.get("name")
            val  = p.get("value")
            if isinstance(name, str):
                out[name] = val
    return out

_IMG_BLOCK_RE = re.compile(
    r"\[IMAGE_CONTEXT\](.*?)\[/IMAGE_CONTEXT\]",
    re.DOTALL | re.IGNORECASE
)

def _parse_image_context(text: str) -> dict:
    """
    Fallback: extract s3Uri, question, language from the [IMAGE_CONTEXT] block in inputText.
    Accepts lines like: s3Uri: <uri>, question: <q>, language: <code>
    """
    m = _IMG_BLOCK_RE.search(text or "")
    if not m:
        return {}
    block = m.group(1)
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    data = {}
    for ln in lines:
        if ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        k = k.strip()
        v = v.strip()
        if k.lower() in ("s3uri", "s3_uri"):
            data["s3Uri"] = v
        elif k.lower() == "question":
            data["question"] = v
        elif k.lower() == "language":
            data["language"] = v
    return data

def _ok_agent_response(action_group: str, api_path: str, http_method: str, body_obj: dict) -> dict:
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

def lambda_handler(event, context):
    # Log only keys to keep it short
    LOG.info("RAW %s", _safe_json({"keys": list((event or {}).keys())}))

    is_agent_tool = isinstance(event, dict) and "actionGroup" in event
    try:
        if is_agent_tool:
            action_group = event.get("actionGroup") or "ImageTools"
            api_path     = event.get("apiPath") or "/analyze-image"
            http_method  = event.get("httpMethod") or "POST"

            # 1) Prefer requestBody JSON
            s3_uri = question = language = None
            req_body_raw = event.get("requestBody") or "{}"
            try:
                body = json.loads(req_body_raw)
            except Exception:
                body = {}
            s3_uri   = body.get("s3Uri")
            question = body.get("question")
            language = body.get("language")

            # 2) If missing, check parameters list (slot-filling style)
            if not s3_uri:
                params = _parse_parameters_list(event.get("parameters"))
                s3_uri   = s3_uri or params.get("s3Uri")
                question = question or params.get("question")
                language = language or params.get("language")

            # 3) If still missing, fallback: parse [IMAGE_CONTEXT] from inputText
            if not s3_uri:
                ctx = _parse_image_context(event.get("inputText") or "")
                if ctx:
                    s3_uri   = ctx.get("s3Uri")
                    question = question or ctx.get("question")
                    language = language or ctx.get("language")

            if not s3_uri:
                LOG.warning("BAD_REQUEST %s", _safe_json({"error": "missing s3Uri"}))
                return {
                    "messageVersion": "1.0",
                    "response": {
                        "actionGroup": action_group,
                        "apiPath": api_path,
                        "httpMethod": http_method,
                        "httpStatusCode": 400,
                        "responseBody": {
                            "application/json": {"body": json.dumps({"error": "missing s3Uri"}, ensure_ascii=False)}
                        }
                    }
                }

            result = _analyze_core(s3_uri, question, language)
            LOG.info("VISION_OK %s", _safe_json({"s3Uri": s3_uri, "preview": result.get("answer", "")[:240]}))
            return _ok_agent_response(action_group, api_path, http_method, result)

        # -------- AWS_PROXY mode (API Gateway) --------
        body_raw = event.get("body")
        body = json.loads(body_raw) if isinstance(body_raw, str) else (body_raw or {})
        s3_uri   = body.get("s3Uri")
        question = body.get("question")
        language = body.get("language")

        if not s3_uri:
            return {"statusCode": 400, "body": json.dumps({"error": "missing s3Uri"})}

        result = _analyze_core(s3_uri, question, language)
        LOG.info("VISION_OK %s", _safe_json({"s3Uri": s3_uri, "preview": result.get("answer", "")[:240]}))
        return {"statusCode": 200, "body": json.dumps(result, ensure_ascii=False)}

    except Exception as e:
        LOG.error("UNEXPECTED %s", str(e))
        if is_agent_tool:
            return {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": event.get("actionGroup") or "ImageTools",
                    "apiPath": event.get("apiPath") or "/analyze-image",
                    "httpMethod": event.get("httpMethod") or "POST",
                    "httpStatusCode": 500,
                    "responseBody": {
                        "application/json": {"body": json.dumps({"error": "unexpected", "detail": str(e)}, ensure_ascii=False)}
                    }
                }
            }
        return {"statusCode": 500, "body": json.dumps({"error": "unexpected", "detail": str(e)})}