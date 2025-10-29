import os
import json
import logging
import urllib.request
from typing import Optional, Tuple, Dict, Any
import boto3
from botocore.exceptions import ClientError

# ---------- Config / Clients ----------
LOG = logging.getLogger()
LOG.setLevel(logging.INFO)

S3_BUCKET = os.environ.get("S3_BUCKET")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
WA_TOKEN_SECRET_NAME = os.environ.get("WA_TOKEN_SECRET_NAME")
WA_PROCESS_FUNCTION = os.environ.get("WA_PROCESS_FUNCTION")

GRAPH_BASE = os.environ.get("GRAPH_BASE", "https://graph.facebook.com/v22.0")

if not S3_BUCKET:
    raise RuntimeError("Missing required env var: S3_BUCKET")
if not VERIFY_TOKEN:
    raise RuntimeError("Missing required env var: VERIFY_TOKEN")
if not WA_TOKEN_SECRET_NAME:
    raise RuntimeError("Missing required env var: WA_TOKEN_SECRET_NAME")
if not WA_PROCESS_FUNCTION:
    raise RuntimeError("Missing required env var: WA_PROCESS_FUNCTION")

s3 = boto3.client("s3")
secrets = boto3.client("secretsmanager")
_lambda = boto3.client("lambda")

# Cache the WA token for the Lambda container lifetime
_WA_TOKEN_CACHE: Optional[str] = None


# ---------- Helpers ----------
def get_wa_token() -> str:
    """Fetch long-lived WA token from Secrets Manager (cached)."""
    global _WA_TOKEN_CACHE
    if _WA_TOKEN_CACHE:
        return _WA_TOKEN_CACHE
    try:
        resp = secrets.get_secret_value(SecretId=WA_TOKEN_SECRET_NAME)
        secret_str = resp.get("SecretString")
        if not secret_str:
            raise RuntimeError("SecretString missing")
        data = json.loads(secret_str)
        token = data.get("token")
        if not token:
            raise RuntimeError("Secret must contain key 'token'")
        _WA_TOKEN_CACHE = token
        return token
    except ClientError as e:
        LOG.error("Failed to read WhatsApp token from Secrets Manager: %s", e)
        raise


def http_get_json(url: str, add_bearer: bool = False) -> dict:
    """GET a JSON resource (optionally with WA bearer)."""
    headers = {}
    if add_bearer:
        headers["Authorization"] = f"Bearer {get_wa_token()}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def http_get_bytes(url: str, add_bearer: bool = False) -> bytes:
    """GET raw bytes (optionally with WA bearer)."""
    headers = {}
    if add_bearer:
        headers["Authorization"] = f"Bearer {get_wa_token()}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch_media_url_and_mime(media_id: str) -> Tuple[str, Optional[str]]:
    """
    Use the Graph API to turn a media_id into an ephemeral download URL and mime_type.
    GET /{media_id}
    """
    meta = http_get_json(f"{GRAPH_BASE}/{media_id}", add_bearer=True)
    # Expected: {"id":"...", "url":"https://...","mime_type":"image/jpeg", ...}
    url = meta.get("url")
    mime = meta.get("mime_type")
    if not url:
        raise RuntimeError(f"No URL returned for media_id={media_id}: {meta}")
    return url, mime


def guess_ext(mime: Optional[str]) -> str:
    mapping = {
        "audio/ogg": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
        "image/jpeg": "jpg",
        "image/png": "png",
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/msword": "doc",
    }
    return mapping.get((mime or "").lower(), "bin")


def s3_put_bytes(key: str, data: bytes, content_type: Optional[str] = None) -> str:
    extra = {"ContentType": content_type} if content_type else {}
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=data, **extra)
    return f"s3://{S3_BUCKET}/{key}"


def store_media_if_any(msg: dict, from_id: str, wa_phone_id: Optional[str]) -> Optional[dict]:
    """
    If the message contains a media_id (audio/image/document), download and upload to S3.
    Returns info dict or None if no media. Includes bucket, key, and s3:// URI.
    """
    mtype = msg.get("type")
    media_id = None
    meta_key = None

    if mtype == "audio":
        meta_key = "audio"
    elif mtype == "image":
        meta_key = "image"
    elif mtype == "document":
        meta_key = "document"

    if meta_key:
        media_id = (msg.get(meta_key) or {}).get("id")

    if not media_id:
        return None

    # 1) Resolve ephemeral URL and mime
    url, mime = fetch_media_url_and_mime(media_id)

    # 2) Download bytes (requires WA bearer)
    blob = http_get_bytes(url, add_bearer=True)

    # 3) Build S3 key
    msg_id = msg.get("id", "unknown")
    ext = guess_ext(mime)
    key = f"whatsapp/{wa_phone_id or 'unknown_wa'}/{from_id}/{msg_id}/{mtype}.{ext}"

    # 4) Upload to S3
    uri = s3_put_bytes(key, blob, content_type=mime)

    LOG.info("MEDIA_SAVED %s", json.dumps({
        "media_id": media_id,
        "mime": mime,
        "s3": uri
    }))

    size_bytes = len(blob)
    extra = {}
    if mtype == "image":
        extra["caption"] = (msg.get("image") or {}).get("caption")
    if mtype == "document":
        extra["filename"] = (msg.get("document") or {}).get("filename")

    return {
        "type": mtype,
        "media_id": media_id,
        "mime": mime,
        "s3_bucket": S3_BUCKET,
        "s3_key": key,
        "s3_uri": uri,           # e.g., s3://bucket/whatsapp/...
        "size_bytes": size_bytes,
        **extra,
    }



def classify_and_log(msg: dict, v_value: dict) -> None:
    """Log a simplified view of the message."""
    mtype = msg.get("type")
    from_id = msg.get("from")
    wa_id = v_value.get("metadata", {}).get("phone_number_id")
    simplified = {"from": from_id, "type": mtype, "wa_phone_number_id": wa_id, "id": msg.get("id")}

    if mtype == "text":
        simplified["text"] = (msg.get("text") or {}).get("body", "")
    elif mtype == "audio":
        simplified["media_id"] = (msg.get("audio") or {}).get("id")
        simplified["mime_type"] = (msg.get("audio") or {}).get("mime_type")
    elif mtype == "image":
        simplified["media_id"] = (msg.get("image") or {}).get("id")
        simplified["caption"] = (msg.get("image") or {}).get("caption")
    elif mtype == "document":
        simplified["media_id"] = (msg.get("document") or {}).get("id")
        simplified["filename"] = (msg.get("document") or {}).get("filename")
    elif mtype == "interactive":
        simplified["interactive"] = msg.get("interactive")

    LOG.info("CLASSIFIED %s", json.dumps(simplified))


def dispatch_to_processor(payload: dict) -> None:
    """
    Fire-and-forget invoke to the middle 'processor' Lambda.
    That function will call Bedrock Agent and then your wa-send Lambda.
    """
    try:
        _lambda.invoke(
            FunctionName=WA_PROCESS_FUNCTION,
            InvocationType="Event",  # async
            Payload=json.dumps(payload).encode("utf-8")
        )
        LOG.info("DISPATCHED %s", json.dumps({"processor": WA_PROCESS_FUNCTION, "msg_id": payload.get("message", {}).get("id")}))
    except Exception as ex:
        LOG.error("ERROR invoking processor lambda: %s", ex)


# ---------- Lambda Handler ----------
def lambda_handler(event, context):
    # Raw log (useful for debugging end-to-end)
    try:
        LOG.info("RAW %s", json.dumps(event))
    except Exception:
        LOG.info("RAW (non-serializable event)")

    # ---- Verification (GET) ----
    method = (event.get("requestContext", {}).get("http", {}) or {}).get("method")
    if method == "GET":
        params = event.get("queryStringParameters") or {}
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return {"statusCode": 200, "body": challenge or ""}
        return {"statusCode": 403, "body": "Verification failed"}

    # ---- Inbound (POST) ----
    body_raw = event.get("body")
    try:
        body = json.loads(body_raw) if isinstance(body_raw, str) else (body_raw or {})
    except Exception:
        LOG.warning("WARN body not JSON")
        # Always return 200 to prevent Meta retries for malformed payloads we can't handle
        return {"statusCode": 200, "body": "ok"}

    entries = body.get("entry", [])
    for e in entries:
        for ch in e.get("changes", []):
            v = ch.get("value", {})
            msgs = v.get("messages", [])
            if not msgs:
                # Could be delivery/read statuses etc.
                LOG.info("INFO non-message webhook %s", json.dumps({"keys": list(v.keys())}))
                continue

            # Common metadata
            wa_phone_id = (v.get("metadata") or {}).get("phone_number_id")
            wa_business_account_id = v.get("messaging_product")  # often "whatsapp"

            for msg in msgs:
                # 1) Log simplified classification
                classify_and_log(msg, v)

                from_id = msg.get("from")  # E.164 without '+'
                msg_type = msg.get("type")
                msg_id = msg.get("id")
                timestamp = msg.get("timestamp")

                # 2) Save media if present
                media_info = None
                try:
                    media_info = store_media_if_any(
                        msg=msg,
                        from_id=from_id,
                        wa_phone_id=wa_phone_id,
                    )
                    if media_info:
                        LOG.info("MEDIA_INFO %s", json.dumps(media_info))
                except Exception as ex:
                    LOG.error("ERROR storing media: %s", ex)

                # 3) Build a normalized payload for the processor Lambda
                #    The processor will decide how to call Bedrock Agent and then wa-send.
                normalized: Dict[str, Any] = {
                    "source": "whatsapp",
                    "wa": {
                        "phone_number_id": wa_phone_id,
                        "business": wa_business_account_id
                    },
                    "message": {
                        "id": msg_id,
                        "type": msg_type,
                        "from": from_id,
                        "timestamp": timestamp,
                    },
                    "raw": msg,  # keep original, in case processor needs extra fields
                }

                if msg_type == "text":
                    normalized["message"]["text"] = (msg.get("text") or {}).get("body", "")

                if msg_type == "interactive":
                    # For buttons/list replies, preserve structured content
                    normalized["message"]["interactive"] = msg.get("interactive")

                if media_info:
                    normalized["message"]["media"] = media_info

                # 4) Dispatch to processor (async). The processor is responsible
                #    for invoking Bedrock Agent and finally calling wa-send.
                dispatch_to_processor(normalized)

    # Always acknowledge to Meta quickly
    return {"statusCode": 200, "body": "ok"}
