import os
import json
import logging
import re
from typing import Dict, Any, Optional

import boto3
from botocore.exceptions import ClientError

LOG = logging.getLogger()
LOG.setLevel(logging.INFO)

REGION = os.environ.get("REGION", "us-east-1")
OUTPUT_BUCKET = os.environ["TRANSCRIBE_OUTPUT_BUCKET"]
OUTPUT_PREFIX = os.environ.get("TRANSCRIBE_OUTPUT_PREFIX", "transcripts/")
TRANSCRIBE_ROLE_ARN = os.environ.get("TRANSCRIBE_ROLE_ARN")  # optional

transcribe = boto3.client("transcribe", region_name=REGION)

# Map MIME to Transcribe media format
MIME_TO_FORMAT = {
    "audio/ogg": "ogg",         # WhatsApp voice notes (opus in ogg)
    "audio/opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "mp4",         # m4a
    "audio/m4a": "mp4",
    "audio/aac": "aac",
    "audio/wav": "wav",
    "audio/flac": "flac",
}

def _safe(s: str, maxlen: int = 300) -> str:
    s = s or ""
    return s[:maxlen]

def _format_from_mime(mime: Optional[str]) -> Optional[str]:
    if not mime:
        return None
    m = mime.split(";")[0].strip().lower()
    return MIME_TO_FORMAT.get(m)

def _s3_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"

def _job_name(from_id: str, message_id: str) -> str:
    # Transcribe job name: letters, numbers, hyphens; <=200 chars
    base = f"wa-{from_id}-{message_id}"
    clean = re.sub(r"[^a-zA-Z0-9-]", "-", base)
    return clean[:200]

def lambda_handler(event, context):
    # Expect normalized payload from inbound-webhook (via wa-process)
    try:
        LOG.info("RAW_EVENT %s", json.dumps({ "keys": list((event or {}).keys()) }))
    except Exception:
        LOG.info("RAW_EVENT (non-serializable)")

    msg = (event or {}).get("message", {})
    media = msg.get("media")
    if not media or media.get("type") != "audio":
        LOG.warning("No audio media in event; nothing to do.")
        return {"statusCode": 200, "body": "ok"}

    from_id = msg.get("from", "unknown")
    message_id = msg.get("id", "unknown")
    mime = media.get("mime")
    input_bucket = media.get("s3_bucket")
    input_key = media.get("s3_key")

    if not input_bucket or not input_key:
        LOG.error("Audio event missing s3_bucket/s3_key")
        return {"statusCode": 200, "body": "ok"}

    media_format = _format_from_mime(mime) or "ogg"  # default safest for WA
    input_uri = _s3_uri(input_bucket, input_key)
    job_name = _job_name(from_id, message_id)

    LOG.info("TRANSCRIBE_START %s", json.dumps({
        "job": job_name,
        "mediaUri": _safe(input_uri),
        "format": media_format,
        "output": f"s3://{OUTPUT_BUCKET}/{OUTPUT_PREFIX}{job_name}.json"
    }))

    kwargs: Dict[str, Any] = {
        "TranscriptionJobName": job_name,
        "Media": {"MediaFileUri": input_uri},
        "OutputBucketName": OUTPUT_BUCKET,
        "OutputKey": f"{OUTPUT_PREFIX}{job_name}.json",
        "IdentifyLanguage": True,
        "LanguageOptions": ["es-US", "es-ES", "en-US", "pt-BR"],
                "MediaFormat": media_format,
    }

    if TRANSCRIBE_ROLE_ARN:
        kwargs["JobExecutionSettings"] = {
            "AllowDeferredExecution": False,
            "DataAccessRoleArn": TRANSCRIBE_ROLE_ARN
        }

    try:
        transcribe.start_transcription_job(**kwargs)
    except ClientError as e:
        LOG.error("StartTranscriptionJob failed: %s", e)
        return {"statusCode": 200, "body": "ok"}

    LOG.info("TRANSCRIBE_JOB_SUBMITTED %s", json.dumps({"job": job_name}))
    return {"statusCode": 200, "body": "ok"}
