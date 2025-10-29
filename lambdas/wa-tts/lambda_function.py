import os
import json
import time
import uuid
import logging
from typing import Dict, Any

import boto3
from botocore.exceptions import ClientError

LOG = logging.getLogger()
LOG.setLevel(logging.INFO)

REGION = os.environ.get("REGION", "us-east-1")
S3_BUCKET = os.environ["S3_BUCKET"]
POLLY_VOICE = os.environ.get("POLLY_VOICE", "Lucia")  # e.g., Lucia, Mia, Matthew, etc.

s3 = boto3.client("s3")
polly = boto3.client("polly", region_name=REGION)

def _s3_put_bytes(key: str, data: bytes, content_type: str) -> str:
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=data, ContentType=content_type)
    return f"s3://{S3_BUCKET}/{key}"

def _s3_presigned_get_url(key: str, expires: int = 600) -> str:
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=expires,
    )

def _polly_lang_for_voice(voice: str) -> str:
    # Reasonable defaults; Polly will auto-fallback if needed
    v = (voice or "").lower()
    if v in ("lucia", "conchita", "enrique"):
        return "es-ES"
    if v in ("mia", "lupe"):
        return "es-MX"
    if v in ("vitória", "camila", "ricardo"):
        return "pt-BR"
    return "en-US"

def _tts_mp3(text: str, voice: str) -> bytes:
    lang = _polly_lang_for_voice(voice)
    resp = polly.synthesize_speech(
        Text=text[:3000],
        OutputFormat="mp3",
        VoiceId=voice,
        Engine="neural",               # falls back if voice doesn’t support neural
        LanguageCode=lang
    )
    return resp["AudioStream"].read()

def lambda_handler(event, context):
    """
    Input: {"text": "<reply to speak>", "to": "5693..."}  # 'to' used only for organizing S3 keys
    Output: {"ok": true, "audio_url": "<https presigned>", "s3_key": "tts/......mp3"}
    """
    LOG.info("RAW %s", json.dumps({"keys": list((event or {}).keys())}))
    text = (event or {}).get("text", "").strip()
    to = (event or {}).get("to", "unknown")

    if not text:
        return {"statusCode": 200, "body": json.dumps({"ok": False, "error": "missing text"})}

    try:
        audio_mp3 = _tts_mp3(text, POLLY_VOICE)
    except ClientError as e:
        LOG.error("Polly synth failed: %s", e)
        return {"statusCode": 200, "body": json.dumps({"ok": False, "error": "polly_failed"})}

    ts = int(time.time())
    key = f"tts/{to}/{ts}-{uuid.uuid4().hex}.mp3"

    _s3_put_bytes(key, audio_mp3, content_type="audio/mpeg")
    url = _s3_presigned_get_url(key, expires=600)

    out = {"ok": True, "audio_url": url, "s3_key": key}
    LOG.info("TTS_READY %s", json.dumps({"s3_key": key}))
    return {"statusCode": 200, "body": json.dumps(out)}
