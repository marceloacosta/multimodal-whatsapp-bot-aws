import os
import json
import logging
import re
from typing import Tuple, Optional

import boto3
from botocore.exceptions import ClientError

LOG = logging.getLogger()
LOG.setLevel(logging.INFO)

s3 = boto3.client("s3")
_lambda = boto3.client("lambda")

# Env: name/ARN of your existing processor
WA_PROCESS_FUNCTION = os.environ["WA_PROCESS_FUNCTION"]

# Matches the job name we used earlier: wa-<from>-<message_id>
JOBNAME_RE = re.compile(r"^wa-([0-9]+)-([A-Za-z0-9_-]+)$")

def _parse_s3_event(record) -> Tuple[str, str]:
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"]
    return bucket, key

def _read_s3_json(bucket: str, key: str) -> dict:
    obj = s3.get_object(Bucket=bucket, Key=key)
    b = obj["Body"].read()
    try:
        return json.loads(b)
    except Exception:
        LOG.error("Invalid JSON at s3://%s/%s", bucket, key)
        return {}

def _extract_jobname_from_key(key: str) -> Optional[str]:
    # Expect keys like: transcripts/wa-<from>-<message_id>.json
    name = key.rsplit("/", 1)[-1]
    if name.endswith(".json"):
        return name[:-5]
    return None

def _extract_ids(job_name: str) -> Tuple[Optional[str], Optional[str]]:
    m = JOBNAME_RE.match(job_name or "")
    if not m:
        return None, None
    from_id, message_id = m.group(1), m.group(2)
    return from_id, message_id

def _extract_transcript(doc: dict) -> str:
    # Standard Amazon Transcribe JSON:
    # { "results": { "transcripts": [ { "transcript": "..." } ] , ... } }
    try:
        transcripts = doc["results"]["transcripts"]
        if transcripts and isinstance(transcripts, list):
            text = transcripts[0].get("transcript", "")
            return (text or "").strip()
    except Exception:
        pass
    return ""

def _invoke_wa_process_as_text(from_id: str, message_id: str, transcript: str):
    # Minimal normalized payload that wa-process already understands
    event = {
        "source": "whatsapp",
        "message": {
            "id": message_id,
            "type": "text",
            "from": from_id,
            "timestamp": None,
            "text": transcript
        },
        # 'raw' is optional here; omitted to keep payload small
    }
    _lambda.invoke(
        FunctionName=WA_PROCESS_FUNCTION,
        InvocationType="Event",
        Payload=json.dumps(event).encode("utf-8"),
    )
    LOG.info("WA_PROCESS_DISPATCHED %s", json.dumps({
        "to": from_id,
        "preview": transcript[:240]
    }))

def lambda_handler(event, context):
    # S3 ObjectCreated notification
    records = event.get("Records", [])
    if not records:
        LOG.warning("No S3 records in event")
        return {"statusCode": 200, "body": "ok"}

    for rec in records:
        bucket, key = _parse_s3_event(rec)
        LOG.info("TRANSCRIPT_ARRIVED %s", json.dumps({"bucket": bucket, "key": key}))

        # 1) Read Transcribe JSON
        doc = _read_s3_json(bucket, key)
        transcript = _extract_transcript(doc)
        if not transcript:
            LOG.warning("Empty transcript for %s/%s", bucket, key)
            continue

        # 2) Recover from_id and message_id from the job name
        job_name = _extract_jobname_from_key(key)
        from_id, message_id = _extract_ids(job_name or "")
        if not (from_id and message_id):
            LOG.warning("Could not parse from/message_id from job name: %s", job_name)
            continue

        # 3) Hand back to wa-process as a text message
        try:
            _invoke_wa_process_as_text(from_id, message_id, transcript)
        except ClientError as e:
            LOG.error("Invoke wa-process failed: %s", e)

    return {"statusCode": 200, "body": "ok"}
