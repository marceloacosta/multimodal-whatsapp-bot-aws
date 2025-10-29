import os
import json
import logging
from typing import Dict, Any, Optional, List

import boto3
from botocore.exceptions import ClientError

# ---------------- Logging ----------------
LOG = logging.getLogger()
LOG.setLevel(logging.INFO)

# ---------------- Env ----------------
BEDROCK_REGION = os.environ["BEDROCK_REGION"]
BEDROCK_AGENT_ID = os.environ["BEDROCK_AGENT_ID"]
BEDROCK_AGENT_ALIAS_ID = os.environ["BEDROCK_AGENT_ALIAS_ID"]

WA_SEND_FUNCTION = os.environ["WA_SEND_FUNCTION"]                      # Lambda name/arn wa-send
WA_AUDIO_TRANSCRIBE_FUNCTION = os.environ.get("WA_AUDIO_TRANSCRIBE_FUNCTION")  # Lambda name/arn wa-audio-transcribe
WA_TTS_FUNCTION = os.environ.get("WA_TTS_FUNCTION")                    # Lambda name/arn wa-tts

# Modelo liviano para clasificar intención de VOZ
INTENT_MODEL_ID = os.environ.get("INTENT_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")

# Logs
LOG_PREVIEW_CHARS = int(os.environ.get("LOG_PREVIEW_CHARS", "240"))
LOG_TRACE_MAX = int(os.environ.get("LOG_TRACE_MAX", "10"))

MEDIA_BUCKET = os.environ.get("MEDIA_BUCKET")  # REQUIRED: Set in Lambda environment variables
if not MEDIA_BUCKET:
    raise ValueError("MEDIA_BUCKET environment variable is required")


# ---------------- Clients ----------------
bedrock_agent = boto3.client("bedrock-agent-runtime", region_name=BEDROCK_REGION)
bedrock_rt = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
_lambda = boto3.client("lambda")


# ---------------- Utils ----------------
def _safe_json(obj: Any, max_len: int = 4000) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    if len(s) > max_len:
        s = s[:max_len] + f"... [truncated {len(s) - max_len} chars]"
    return s


def _read_text_from_event(event: Dict[str, Any]) -> str:
    """
    Extrae texto del payload normalizado (texto o interactive).
    """
    msg = (event or {}).get("message", {})
    text = (msg.get("text") or "").strip()

    if not text and "interactive" in msg:
        it = msg["interactive"]
        text = (
            (it.get("button_reply") or {}).get("title")
            or (it.get("list_reply") or {}).get("title")
            or ""
        ).strip()

    return text or "Hola"


def _invoke_agent(session_id: str, user_text: str, user_phone: str = None) -> Dict[str, Any]:
    """
    Invoca Bedrock Agent en streaming y concatena la respuesta final.
    Devuelve {"text": str, "chunk_count": int, "trace_events": List[dict]}.
    """
    LOG.info("AGENT_INVOKE %s", _safe_json({
        "region": BEDROCK_REGION,
        "agentId": BEDROCK_AGENT_ID,
        "aliasId": BEDROCK_AGENT_ALIAS_ID,
        "sessionId": session_id,
        "inputPreview": user_text[:LOG_PREVIEW_CHARS],
        "userPhone": user_phone,
    }, 1200))

    # Pass user phone and original text in sessionAttributes so sub-agents can access them
    session_attrs = {}
    if user_phone:
        session_attrs["userPhone"] = user_phone
        session_attrs["originalUserText"] = user_text[:500]  # Pass original user message

    try:
        resp = bedrock_agent.invoke_agent(
            agentId=BEDROCK_AGENT_ID,
            agentAliasId=BEDROCK_AGENT_ALIAS_ID,
            sessionId=session_id,
            inputText=user_text,
            enableTrace=True,
            sessionState={
                "sessionAttributes": session_attrs
            } if session_attrs else {}
        )
    except ClientError as e:
        LOG.error("InvokeAgent failed: %s", e)
        raise

    text_parts: List[str] = []
    chunk_count = 0
    trace_summaries: List[Dict[str, Any]] = []

    completion_stream = resp.get("completion")
    if completion_stream is None:
        LOG.warning("No 'completion' stream in agent response")
        return {"text": "", "chunk_count": 0, "trace_events": []}

    for ev in completion_stream:
        if isinstance(ev, dict) and "chunk" in ev:
            b = ev["chunk"].get("bytes")
            if b:
                if isinstance(b, (bytes, bytearray)):
                    piece = b.decode("utf-8", errors="ignore")
                elif isinstance(b, str):
                    piece = b
                else:
                    piece = str(b)
                if piece:
                    text_parts.append(piece)
                    chunk_count += 1

        elif isinstance(ev, dict) and "trace" in ev:
            tr = ev["trace"]
            summary = {
                "type": tr.get("type"),
                "eventType": tr.get("eventType"),
            }
            tool = tr.get("tool")
            if isinstance(tool, dict):
                summary["toolName"] = tool.get("name")
                summary["toolInvocation"] = tool.get("invocationId")
            observation = tr.get("observation")
            if observation:
                summary["observationPreview"] = _safe_json(observation, 500)

            trace_summaries.append(summary)
            if len(trace_summaries) <= LOG_TRACE_MAX:
                LOG.info("AGENT_TRACE %s", _safe_json(summary, 1200))

        elif isinstance(ev, dict) and "guardrail" in ev:
            LOG.info("AGENT_GUARDRAIL %s", _safe_json(ev.get("guardrail"), 1200))
        else:
            LOG.debug("AGENT_EVENT_OTHER %s", _safe_json(ev, 800))

    final_text = "".join(text_parts).strip()

    LOG.info("AGENT_SUMMARY %s", _safe_json({
        "chunks": chunk_count,
        "finalPreview": final_text[:LOG_PREVIEW_CHARS],
        "tracesCaptured": len(trace_summaries),
    }, 1200))

    return {"text": final_text, "chunk_count": chunk_count, "trace_events": trace_summaries}


def _send_whatsapp_text(to_no_plus: str, text: str) -> None:
    payload = {"to": to_no_plus, "text": text[:4096]}
    _lambda.invoke(
        FunctionName=WA_SEND_FUNCTION,
        InvocationType="Event",
        Payload=json.dumps(payload).encode("utf-8"),
    )


def _send_whatsapp_audio(to_no_plus: str, audio_url: str) -> None:
    payload = {"to": to_no_plus, "audio_url": audio_url}
    _lambda.invoke(
        FunctionName=WA_SEND_FUNCTION,
        InvocationType="Event",
        Payload=json.dumps(payload).encode("utf-8"),
    )


def _tts_get_url_sync(to_no_plus: str, text: str) -> Optional[str]:
    """
    Invoca wa-tts de forma síncrona y devuelve audio_url o None.
    """
    if not WA_TTS_FUNCTION:
        LOG.warning("WA_TTS_FUNCTION not configured")
        return None
    try:
        resp = _lambda.invoke(
            FunctionName=WA_TTS_FUNCTION,
            InvocationType="RequestResponse",
            Payload=json.dumps({"to": to_no_plus, "text": text[:3000]}).encode("utf-8"),
        )
        payload_bytes = resp.get("Payload").read()
        outer = json.loads(payload_bytes or b"{}")
        body = outer.get("body")
        data = json.loads(body) if isinstance(body, str) else (body or {})
        if data.get("ok") and data.get("audio_url"):
            return data["audio_url"]
        LOG.warning("TTS returned no audio_url: %s", _safe_json(data, 800))
        return None
    except Exception as e:
        LOG.error("TTS invoke failed: %s", e)
        return None


def _classify_voice_intent(user_text: str) -> bool:
    """
    Clasifica con un LLM liviano si el usuario pidió explícitamente VOZ.
    Responde True/False según JSON {"voice": <bool>}. Fallback = False.
    """
    txt = (user_text or "").strip()
    if not txt:
        return False

    system = (
        "You are an intent classifier. Decide ONLY if the user explicitly asks to receive the reply as VOICE/AUDIO. "
        "Do NOT infer unless it's explicit. "
        "Return ONLY a compact JSON object: {\"voice\": true|false} with no extra text."
    )
    user = (
        "User message:\n"
        f"{txt}\n\n"
        "Answer strictly as JSON with the single key 'voice'."
    )

    try:
        # Converse API (modelo Anthropic en Bedrock)
        resp = bedrock_rt.converse(
            modelId=INTENT_MODEL_ID,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"temperature": 0.0, "maxTokens": 32},
        )

        # Extraer texto de la salida
        out = resp.get("output", {})
        msg = out.get("message") or (out.get("messages") or [{}])[0]
        content = msg.get("content", [])
        text_chunks = [c.get("text") for c in content if isinstance(c, dict) and c.get("text")]
        raw = (text_chunks[0] if text_chunks else "").strip()

        obj = json.loads(raw) if raw else {}
        return bool(obj.get("voice") is True)
    except Exception as e:
        LOG.warning("INTENT_LLM_FAIL %s", str(e))
        return False


# ---------------- Handler ----------------
def lambda_handler(event, context):
    LOG.info("RAW_EVENT %s", _safe_json({"keys": list((event or {}).keys())}, 400))

    # Payload normalizado desde inbound-webhook
    msg = (event or {}).get("message", {})
    from_id: Optional[str] = msg.get("from")
    media = msg.get("media")

    # Audio entrante -> lanzar transcripción y salir
    if media and media.get("type") == "audio":
        if not WA_AUDIO_TRANSCRIBE_FUNCTION:
            LOG.error("WA_AUDIO_TRANSCRIBE_FUNCTION not configured")
            return {"statusCode": 200, "body": "ok"}

        _lambda.invoke(
            FunctionName=WA_AUDIO_TRANSCRIBE_FUNCTION,
            InvocationType="Event",
            Payload=json.dumps(event).encode("utf-8"),
        )
        return {"statusCode": 200, "body": "ok"}

    if not from_id:
        LOG.warning("No 'from' in message; skipping")
        return {"statusCode": 200, "body": "ok"}

    session_id = f"wa-{from_id}"

    # 1) Texto del usuario
    user_text = _read_text_from_event(event)
    LOG.info("USER_TEXT %s", _safe_json({"from": from_id, "preview": user_text[:LOG_PREVIEW_CHARS]}, 400))
    
    
    # 2) Si llegó imagen, adjunta contexto para que el Agente use la herramienta analyzeImage
    if media and media.get("type") == "image":
        s3_key = (media or {}).get("s3_key")
        if MEDIA_BUCKET and s3_key:
            s3_uri = f"s3://{MEDIA_BUCKET}/{s3_key}"
            image_ctx = (
                "\n\n[IMAGE_CONTEXT]\n"
                f"s3Uri: {s3_uri}\n"
                f"question: {user_text}\n"
                "[/IMAGE_CONTEXT]"
            )
            user_text = (user_text or "").strip() + image_ctx
            LOG.info("IMAGE_CONTEXT_ATTACHED %s", _safe_json({"s3Uri": s3_uri}, 400))
        else:
            LOG.warning("IMAGE_CONTEXT_SKIPPED missing MEDIA_BUCKET or s3_key")
    

    # 3) Invocar agente Bedrock (pass phone number via sessionAttributes)
    try:
        agent_out = _invoke_agent(session_id=session_id, user_text=user_text, user_phone=from_id)
        agent_reply = agent_out.get("text", "")
    except Exception as ex:
        LOG.error("Agent error: %s", ex)
        agent_reply = ""

    if not agent_reply:
        agent_reply = "Lo siento, no pude generar una respuesta."

    # 4) ¿El usuario pidió VOZ? -> clasificador LLM
    wants_voice = _classify_voice_intent(user_text)
    LOG.info("VOICE_INTENT %s", _safe_json({"wants_voice": wants_voice}, 200))

    if wants_voice:
        audio_url = _tts_get_url_sync(to_no_plus=from_id, text=agent_reply)
        if audio_url:
            _send_whatsapp_audio(to_no_plus=from_id, audio_url=audio_url)
            LOG.info("WA_AUDIO_DISPATCHED %s", _safe_json({"to": from_id, "urlPreview": audio_url[:120]}, 400))
            return {"statusCode": 200, "body": "ok"}
        # Si TTS falla, caemos a texto:
        LOG.warning("Falling back to text because TTS failed")

    # 5) Check if image was already sent (agent responds with ✅)
    agent_reply_clean = agent_reply.strip()
    if agent_reply_clean == "✅":
        LOG.info("IMAGE_ALREADY_SENT %s", _safe_json({"to": from_id}, 200))
        return {"statusCode": 200, "body": "ok"}

    # 6) Send agent response as text
    _send_whatsapp_text(to_no_plus=from_id, text=agent_reply)
    LOG.info("WA_TEXT_DISPATCHED %s", _safe_json({"to": from_id, "preview": agent_reply[:LOG_PREVIEW_CHARS]}, 400))
    return {"statusCode": 200, "body": "ok"}
